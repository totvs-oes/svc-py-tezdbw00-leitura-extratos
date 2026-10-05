# Serviço de Leitura de Extratos — AEROFLEX

API FastAPI que lê extratos bancários em PDF (PyMuPDF) e devolve os lançamentos em JSON, com conferência de saldo.
Consumida pelo robô de conciliação: repo irmão `../bot-py-tezdbw00-conciliacao-bancaria`. O contrato da API está documentado lá, em `.claude/skills/conciliacao-aeroflex/references/api-extratos.md`.

## Comandos

```
python -m venv venv && venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py        # API em http://localhost:5000, docs em /docs
powershell.exe -NoProfile -ExecutionPolicy Bypass -File cliente\enviar_extratos.ps1 -Token <TOKEN>
```

`.env` (modelo em `.env.example`): `TOKEN` (Bearer das rotas), `OLLAMA_BASE_URL`, `OLLAMA_MODEL` (padrão `qwen3:1.7b`), `SFTP_*` (servidor do cliente).
`requirements.txt` está em **UTF-16** (gerado por `pip freeze` no PowerShell): ao editar, preserve a codificação.

### Docker (produção)

```
docker compose up -d --build                 # API na porta 5000; cria a rede "tezdbw00" usada pelo robô
docker compose --profile ia up -d --build    # + Ollama em container (fallback de IA)
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
llm/llm.py                     fallback com Ollama (structured output, uma chamada por página)
schemas/extrato.py             contrato da resposta
routers/                       sftp_router (listar e ler do SFTP), extratos_router (upload), transcribe_router (teste)
cliente/                       script que roda no Windows Server do cliente: entrada -> API -> lidos | erro
```

Layouts: Tarifas ABC, ABC, Caixa, Banco do Brasil, Bradesco, Itaú, Safra, Santander, Daycoval.

## Convenções

- Código e nomes em português.
- **Banco novo = novo `Layout` em `services/layouts.py`**, com os cabeçalhos das colunas exatamente como no PDF. Valide com os PDFs de `docs_example/`: a conferência precisa dar `ok: true`.
- **A conferência de saldo é o critério de qualidade**: saldo anterior + créditos − débitos = saldo final, ao centavo. Nunca force a conferência a passar. Movimentação não listada (`saldo_da_conta`) só conta como explicada se houver aplicação automática no extrato (caso do Itaú).
- `valor` sempre positivo + `operacao` (`credito`/`debito`). O sinal ou sufixo C/D do próprio PDF prevalece sobre a coluna e sobre a IA.
- IA só como fallback: `temperature=0`, `reasoning=False`, `num_ctx=16384` (o padrão do Ollama trunca o texto sem avisar).
- Scripts em `cliente/`: compatíveis com **Windows PowerShell 5.1** e sem acentos nos `.ps1` (o 5.1 lê arquivo sem BOM como ANSI).
- Mudou a resposta (`schemas/extrato.py`)? Atualize no repo do robô o `api-extratos.md` e a fixture `tests/fixtures/extratos_exemplo.json`.
