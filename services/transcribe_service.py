from collections import defaultdict
from pathlib import Path
from typing import Optional, Union

from schemas.extrato import Conferencia, ExtratoConta, Lancamento, MovimentacaoNaoListada
from services.layouts import ResultadoLayout, extrair_com_layout, identificar_layout
from services.normalizacao import (ano_do_extrato, eh_linha_de_saldo, identificar_banco,
                                   normalizar_data, parse_saldo, parse_valor)
from services.pdf_service import extrair_linhas, renderizar

# Arquivos estáticos para teste.
PASTA_EXEMPLOS = Path(__file__).resolve().parent.parent / "docs_example"
SEM_LAYOUT = ("TARIFAS BB", "TARIFAS ITAU")
ARQUIVOS_TESTE = sorted(p for p in PASTA_EXEMPLOS.glob("*.pdf") if not p.name.upper().startswith(SEM_LAYOUT))


def sem_leitura(nome_arquivo: str, aviso: str) -> tuple[str, ExtratoConta]:
    extrato = ExtratoConta(arquivo=nome_arquivo, metodo="nenhum", conta=None, lancamentos=[],
                           aviso=aviso, conferencia=conferir([], None, None))
    return f"banco_{identificar_banco('', nome_arquivo) or 'desconhecido'}", extrato


def transcrever_arquivo(file_path: Path) -> tuple[str, ExtratoConta]:
    return transcrever_pdf(file_path.name, str(file_path))


def transcrever_pdf(nome_arquivo: str, origem: Union[str, bytes]) -> tuple[str, ExtratoConta]:
    """Lê um extrato, a partir do caminho do arquivo ou do conteúdo em memória (upload)."""
    linhas_por_pagina = extrair_linhas(origem)
    paginas = ["\n".join(renderizar(linha) for linha in pagina) for pagina in linhas_por_pagina]
    texto_completo = "\n".join(paginas)
    ano = ano_do_extrato(texto_completo)

    # PDF sem camada de texto (escaneado ou exportado como imagem): nem layout nem IA conseguem ler
    if not texto_completo.strip():
        return sem_leitura(nome_arquivo, "PDF sem texto (escaneado ou exportado como imagem). "
                                          "É necessário OCR para ler este arquivo.")

    # Layout conhecido: parser determinístico. Desconhecido: IA como fallback
    layout = identificar_layout(nome_arquivo, texto_completo)
    if layout:
        resultado = extrair_com_layout(linhas_por_pagina, layout, texto_completo, ano)
        codigo_banco, metodo = layout.codigo_banco, f"layout {layout.nome}"
    else:
        resultado = _extrair_com_ia(paginas, ano)
        codigo_banco, metodo = identificar_banco(texto_completo, nome_arquivo) or "desconhecido", "ia"

    extrato = ExtratoConta(
        arquivo=nome_arquivo,
        metodo=metodo,
        conta=resultado.conta,
        lancamentos=resultado.lancamentos,
        conferencia=conferir(resultado.lancamentos, resultado.saldo_anterior, resultado.saldo_final,
                             resultado.nao_listadas),
    )
    return f"banco_{codigo_banco}", extrato


def _extrair_com_ia(paginas: list[str], ano: Optional[str]) -> ResultadoLayout:
    from llm.llm import extrair_pagina  # só carrego a IA quando eu realmente preciso

    # 1) IA: uma chamada por página (mantém o contexto pequeno e a precisão alta)
    extracoes = [extrair_pagina(pagina) for pagina in paginas if pagina.strip()]

    # 2) Python: normalização determinística do que a IA devolveu
    # Se o extrato marca os débitos com "-" (Santander, Itaú, Bradesco, ABC...), um valor
    # sem sinal é crédito: não depende da interpretação da IA
    usa_sinal_negativo = any(parse_valor(item.valor)[1] == "debito" and "-" in item.valor
                             for extracao in extracoes for item in extracao.lancamentos)

    lancamentos: list[Lancamento] = []
    ultima_data: Optional[str] = None
    for extracao in extracoes:
        for item in extracao.lancamentos:
            valor, operacao_pelo_texto = parse_valor(item.valor)
            if not valor or eh_linha_de_saldo(item.historico):
                continue

            # Bancos como o Bradesco só mostram a data na primeira linha do dia
            data = normalizar_data(item.data, ano) or ultima_data
            ultima_data = data

            if not operacao_pelo_texto and usa_sinal_negativo:
                operacao_pelo_texto = "credito"

            lancamentos.append(Lancamento(
                data=data,
                historico=" ".join(item.historico.split()),
                # sinal/sufixo C-D do próprio valor é mais confiável que a interpretação da IA
                operacao=operacao_pelo_texto or item.operacao,
                valor=valor,
            ))

    # Saldos só valem de páginas com lançamentos: páginas de resumo (ex.: "Saldo Disponível
    # Total" do Santander, que soma investimentos) não são o saldo final da tabela
    paginas_com_lancamentos = [e for e in extracoes if e.lancamentos]
    return ResultadoLayout(
        conta=next((e.conta for e in extracoes if e.conta), None),
        lancamentos=lancamentos,
        saldo_anterior=next((parse_saldo(e.saldo_anterior) for e in paginas_com_lancamentos if e.saldo_anterior), None),
        saldo_final=next((parse_saldo(e.saldo_final) for e in reversed(paginas_com_lancamentos) if e.saldo_final), None),
    )


def conferir(lancamentos: list[Lancamento], saldo_anterior: Optional[float], saldo_final: Optional[float],
             nao_listadas: Optional[list[MovimentacaoNaoListada]] = None) -> Conferencia:
    """Confere se saldo anterior + créditos - débitos (+ movimentações não listadas) bate com o saldo final.

    É o principal indicador de que nenhum lançamento foi pulado, duplicado ou invertido.
    Movimentações não listadas sem explicação (aplicação automática) reprovam a conferência.
    """
    nao_listadas = nao_listadas or []
    creditos = round(sum(l.valor for l in lancamentos if l.operacao == "credito"), 2)
    debitos = round(sum(l.valor for l in lancamentos if l.operacao == "debito"), 2)

    diferenca = None
    if saldo_anterior is not None and saldo_final is not None:
        ajustes = sum(m.valor for m in nao_listadas)
        diferenca = round(saldo_anterior + creditos - debitos + ajustes - saldo_final, 2)

    return Conferencia(
        saldo_anterior=saldo_anterior,
        saldo_final=saldo_final,
        total_creditos=creditos,
        total_debitos=debitos,
        movimentacoes_nao_listadas=nao_listadas,
        diferenca=diferenca,
        ok=None if diferenca is None else abs(diferenca) < 0.01 and all(m.explicada for m in nao_listadas),
    )


def agrupar_por_banco(extratos: list[tuple[str, ExtratoConta]]) -> dict[str, list[ExtratoConta]]:
    resultado: dict[str, list[ExtratoConta]] = defaultdict(list)
    for chave, extrato in extratos:
        resultado[chave].append(extrato)
    return dict(resultado)


def transcrever(filtro: Optional[str] = None) -> dict[str, list[ExtratoConta]]:
    arquivos = [a for a in ARQUIVOS_TESTE if not filtro or filtro.upper() in a.name.upper()]
    return agrupar_por_banco([transcrever_arquivo(arquivo) for arquivo in arquivos])


def transcrever_uploads(arquivos: list[tuple[str, bytes]]) -> dict[str, list[ExtratoConta]]:
    """Lê os PDFs enviados por upload: lista de (nome do arquivo, conteúdo)."""
    return agrupar_por_banco([transcrever_pdf(nome, conteudo) for nome, conteudo in arquivos])
