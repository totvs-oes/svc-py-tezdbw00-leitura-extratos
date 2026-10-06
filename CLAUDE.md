# Serviço de Leitura de Extratos — AEROFLEX

API FastAPI que lê extratos bancários em PDF (PyMuPDF) e devolve os lançamentos em JSON, com conferência de saldo.
Consumida pelo robô de conciliação: repo irmão `../bot-py-tezdbw00-conciliacao-bancaria`. O contrato da API está documentado lá, em `.claude/skills/conciliacao-aeroflex/references/api-extratos.md`.

## Comandos

```
python -m venv venv && venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py        # API em http://localhost:5000, docs em /docs
powershell.exe -NoProfile -ExecutionPolicy Bypass -File cliente\enviar_extratos.ps1 -Token <TOKEN>
venv\Scripts\pip install -r requirements-dev.txt && venv\Scripts\python -m pytest   # testes
venv\Scripts\python -m tests.regressao   # regrava a referência dos layouts (só após mudar um layout DE PROPÓSITO)
```

Testes: `tests/test_layouts.py` compara a leitura de cada PDF de `docs_example/` com `tests/fixtures/esperado_layouts.json` (totais, saldos e SHA-256 dos lançamentos, sem o texto dos extratos); sem a pasta, esses testes são pulados. A IA nunca é chamada nos testes.

`.env` (modelo em `.env.example`): `TOKEN` (Bearer das rotas), `LLM_BASE_API_URL` (proxy de IA da TOTVS), `TOKEN_API_LLM`, `LLM_MODEL` (padrão `gpt-4o`), `SFTP_*` (servidor do cliente).
`requirements.txt` está em **UTF-16** (gerado por `pip freeze` no PowerShell): ao editar, preserve a codificação.

### Docker (produção)

```
docker compose up -d --build                 # API na porta 5000; cria a rede "tezdbw00" usada pelo robô
```

- A imagem **não** leva `docs_example/` (extratos reais do cliente), `cliente/`, `sftp/` (chave e known_hosts) nem `.env` — ver `.dockerignore`.
- Credenciais do SFTP em `./sftp/` (fora do git), montada em `/run/sftp` somente leitura. Passo a passo no topo do `docker-compose.yml`.
- `env_file` com `format: raw`: o Compose não interpreta `$` nos valores do `.env`.
- Suba este compose antes do robô (a rede `tezdbw00` nasce aqui).

## Rotas

- `GET /sftp/listar?caminho=` — lista subpastas e PDFs de uma pasta do SFTP do cliente.
- `POST /extratos/sftp` — produção. JSON `{"arquivos": [caminhos]}`: baixa do SFTP e lê cada PDF. Arquivo com problema volta com `metodo: "nenhum"` e `aviso` (não derruba os outros). É a rota que o robô usa (`FONTE_EXTRATOS=sftp`).
- `POST /extratos` — upload `multipart/form-data`, campo `arquivos` (um ou mais PDFs, máx. 20 MB). Usada pelo script do cliente (`cliente/`) e pelo robô em modo local.
- `POST /transcribe` — só teste: lê os PDFs fixos de `docs_example/` (filtro opcional `?arquivo=ABC`).

Resposta: `{"banco_<COMPE>": [ExtratoConta]}` — ver `schemas/extrato.py`.

### SFTP (`services/sftp_service.py`)

- Caminhos sempre **relativos** à `SFTP_PASTA_BASE`; absoluto ou com `..` é recusado (400).
- Chave do servidor verificada contra `SFTP_KNOWN_HOSTS` (`RejectPolicy`): servidor desconhecido ou com chave diferente não conecta. Gerar a linha: `python -m services.sftp_service known-hosts <host> [porta]` e conferir a impressão digital com o TI do cliente.
- Autenticação por chave (`SFTP_CHAVE`) de preferência; senha (`SFTP_SENHA`) também funciona.
- Erros: 503 SFTP não configurado, 502 falha de conexão/autenticação/chave, 404 pasta inexistente.
- No Windows Server do cliente o caminho fica no formato `/D:/A PAGAR/AEROFLEX` (OpenSSH).

## Arquitetura

```
services/pdf_service.py        palavras com coordenadas -> linhas; junta células quebradas; corrige página rotacionada
services/layouts.py            um Layout por banco (cabeçalhos das colunas -> faixas X); parser próprio quando não há tabela (Daycoval)
services/normalizacao.py       valores/datas em formato BR, identificação do banco (código COMPE)
services/sftp_service.py       conexão SFTP com o servidor do cliente: listar e baixar (em memória)
services/transcribe_service.py orquestra: sem texto -> aviso | layout conhecido -> parser | senão -> IA; conferência de saldo
llm/llm.py                     fallback com IA: ChatOpenAI no proxy da TOTVS (structured output json_schema, uma chamada por página)
schemas/extrato.py             contrato da resposta
routers/                       sftp_router (listar e ler do SFTP), extratos_router (upload), transcribe_router (teste)
cliente/                       script que roda no Windows Server do cliente: entrada -> API -> lidos | erro
```

Layouts: Tarifas ABC, ABC, Caixa, Banco do Brasil, Bradesco, Tarifas Itaú, Itaú, Safra, Santander, Daycoval.

- **Tarifas Itaú** (`extrair_tarifas_itau`): relatório "Movimentação de Títulos" (arquivo `TARIFAS ITAU`), detalhe da linha `TAR/CUSTAS COBRANCA` do extrato. Uma tarifa por boleto: código `01` (valor em "Outros Valores") e histórico `TM` (valor em "Crédito/Débito"). Conferência = soma das tarifas == "Total Deduções" do resumo (vai em `saldo_anterior`, com `saldo_final` 0). As palavras são reagrupadas pela altura real (a 1ª linha de cada página sai grudada no cabeçalho).

## Convenções

- Código e nomes em português.
- **Banco novo = novo `Layout` em `services/layouts.py`**, com os cabeçalhos das colunas exatamente como no PDF. Valide com os PDFs de `docs_example/`: a conferência precisa dar `ok: true`.
- **Identificação do banco/layout só pelo nome do arquivo + cabeçalho da 1ª página + rodapés** (`normalizacao.zona_de_identificacao`). O corpo do extrato cita os bancos das contrapartes ("Pix ... CAIXA ECONOMICA FEDERAL (0104)"). E um layout só é aplicado se o cabeçalho da tabela dele existir no PDF; senão o arquivo vai para a IA.
- **A conferência de saldo é o critério de qualidade**: saldo anterior + créditos − débitos = saldo final, ao centavo. Nunca force a conferência a passar. Movimentação não listada (`saldo_da_conta`) só conta como explicada se houver aplicação automática no extrato (caso do Itaú).
- `valor` sempre positivo + `operacao` (`credito`/`debito`). O sinal ou sufixo C/D do próprio PDF prevalece sobre a coluna e sobre a IA.
- IA só como fallback: `temperature=0`. O cliente é criado no primeiro uso (a API sobe sem `TOKEN_API_LLM`). Falhas do proxy viram `ErroIA` (`llm/erros.py`): 503 no upload, aviso por arquivo no SFTP.
- O texto das páginas sem layout vai para o proxy de IA (fora da VM). PDFs com layout nunca saem do servidor.
- Scripts em `cliente/`: compatíveis com **Windows PowerShell 5.1** e sem acentos nos `.ps1` (o 5.1 lê arquivo sem BOM como ANSI).
- Mudou a resposta (`schemas/extrato.py`)? Atualize no repo do robô o `api-extratos.md` e a fixture `tests/fixtures/extratos_exemplo.json`.
