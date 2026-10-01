"""Layouts conhecidos de extrato: um parser determinístico por banco.

Cada layout descreve as colunas da tabela de lançamentos pelo texto do cabeçalho.
A posição X de cada cabeçalho no PDF define a "faixa" da coluna, e cada palavra
de uma linha vai para a coluna em que cai. Não há IA envolvida: o resultado é exato
e instantâneo. PDFs que não casam com nenhum layout caem no fallback com IA.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from schemas.extrato import Lancamento, MovimentacaoNaoListada
from services.normalizacao import (eh_linha_de_saldo, normalizar_data, parse_saldo,
                                   parse_valor, sem_acentos)
from services.pdf_service import LARGURA_CARACTERE, Linha, renderizar

RE_DINHEIRO = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}[-+]?|-?\d+,\d{2}[-+]?")
RE_DATA = re.compile(r"\d{2}/\d{2}(?:/\d{4})?")

# Papel de cada coluna
DATA, HISTORICO, CONCATENAR, VALOR, CREDITO, DEBITO, SALDO, IGNORAR = (
    "data", "historico", "concatenar", "valor", "credito", "debito", "saldo", "ignorar")
COLUNAS_DE_VALOR = (VALOR, CREDITO, DEBITO, SALDO)


@dataclass
class Coluna:
    cabecalho: str            # texto do cabeçalho no PDF (ex.: "Nr. Doc."); alternativas separadas por "|"
    papel: str                # DATA, HISTORICO, CONCATENAR, VALOR...
    centralizada: bool = False  # cabeçalho centralizado: o conteúdo começa antes do X do cabeçalho
    numerica: bool = False      # coluna ignorada que contém valores monetários (ex.: "Valor unitário")


@dataclass
class Layout:
    nome: str
    codigo_banco: str
    identificacao: str                  # regex no nome do arquivo + texto (sem acentos, maiúsculo)
    colunas: list[Coluna]
    conta: str                          # regex com um grupo para o número da conta
    fim_da_tabela: Optional[str] = None  # regex da linha que encerra a tabela
    inicio_dos_lancamentos: Optional[str] = None  # só considera lançamentos após essa linha
    operacao_padrao: Optional[str] = None         # ex.: relatório de tarifas é sempre débito
    anexar_linhas_sem_valor: bool = False         # BB: complemento do histórico vem na linha de baixo
    conferir_saldo: bool = True
    # Linhas que informam o saldo da conta corrente ao longo do extrato (pontos de controle).
    # Se o saldo corrido divergir delas, há movimentação que o banco não listou.
    saldo_da_conta: Optional[str] = None
    # Históricos que indicam aplicação automática (justificam a movimentação não listada)
    aplicacao_automatica: Optional[str] = None


LAYOUTS: list[Layout] = [
    Layout(
        nome="Tarifas ABC", codigo_banco="0246",
        identificacao=r"RELATORIO DE TARIFAS",
        colunas=[Coluna("Movimento", IGNORAR), Coluna("Data da transação", DATA),
                 Coluna("Tipo da tarifa", HISTORICO), Coluna("Data do debito", IGNORAR),
                 Coluna("Quantidade", IGNORAR), Coluna("Valor unitário", IGNORAR, numerica=True),
                 Coluna("Valor total", VALOR), Coluna("Situação", IGNORAR),
                 Coluna("Personalizada", IGNORAR)],
        conta=r"Conta:\s*(\d+)",
        operacao_padrao="debito", conferir_saldo=False,
    ),
    Layout(
        nome="ABC", codigo_banco="0246",
        identificacao=r"BANCO ABC|ABC BRASIL",
        colunas=[Coluna("Data", DATA), Coluna("Quantidade|Qtd", IGNORAR), Coluna("Histórico", HISTORICO),
                 Coluna("Operação", IGNORAR), Coluna("Valor (R$)", VALOR), Coluna("Saldo", SALDO)],
        conta=r"Conta:\s*(\d+)|\b(00\d{8})\b",
        fim_da_tabela=r"^CANAL:|^OS SALDOS",
    ),
    Layout(
        nome="Caixa", codigo_banco="0104",
        identificacao=r"CAIXA",
        colunas=[Coluna("Data Mov.", DATA), Coluna("Nr. Doc.", CONCATENAR), Coluna("Histórico", HISTORICO),
                 Coluna("Valor", VALOR), Coluna("Saldo", SALDO)],
        conta=r"Conta:\s*([^\n]+)",
        inicio_dos_lancamentos=r"^LANCAMENTOS DO DIA",
        fim_da_tabela=r"^SAC CAIXA",
    ),
    Layout(
        nome="Banco do Brasil", codigo_banco="0001",
        identificacao=r"BANCO DO BRASIL|BB CASH",
        colunas=[Coluna("Dt. balancete", DATA), Coluna("Ag. origem", IGNORAR), Coluna("Lote", IGNORAR),
                 Coluna("Histórico", HISTORICO), Coluna("Documento", IGNORAR, centralizada=True),
                 Coluna("Valor R$", VALOR), Coluna("Saldo", SALDO)],
        conta=r"Conta corrente\s+(\d[\d-]*)",
        fim_da_tabela=r"^LANCAMENTOS FUTUROS",
        anexar_linhas_sem_valor=True,
    ),
    Layout(
        nome="Bradesco", codigo_banco="0237",
        identificacao=r"BRADESCO",
        colunas=[Coluna("Data", DATA), Coluna("Lançamento", HISTORICO), Coluna("Dcto.", CONCATENAR),
                 Coluna("Crédito (R$)", CREDITO), Coluna("Débito (R$)", DEBITO), Coluna("Saldo (R$)", SALDO)],
        conta=r"CC:\s*(\S+)",
        fim_da_tabela=r"^TOTAL\b",
    ),
    Layout(
        nome="Itaú", codigo_banco="0341",
        identificacao=r"ITAU",
        colunas=[Coluna("Data", DATA), Coluna("Lançamentos", HISTORICO), Coluna("Razão Social", IGNORAR),
                 Coluna("CNPJ/CPF", IGNORAR), Coluna("Valor (R$)", VALOR), Coluna("Saldo (R$)", SALDO)],
        conta=r"Conta\s+(\d[\d-]*)",
        fim_da_tabela=r"^AVISO",
        # O Itaú aplica/resgata automaticamente ("Aplic Aut Mais") sem listar como lançamento:
        # só os saldos do dia mostram o efeito
        saldo_da_conta=r"^SALDO (ANTERIOR|MOVIMENTACAO CONTA|EM CONTA CORRENTE)",
        aplicacao_automatica=r"APLIC",
    ),
    Layout(
        nome="Safra", codigo_banco="0422",
        identificacao=r"SAFRA",
        colunas=[Coluna("Data", DATA), Coluna("Lançamento", HISTORICO), Coluna("Complemento", CONCATENAR),
                 Coluna("Nº Documento", CONCATENAR), Coluna("Valor (R$)", VALOR)],
        conta=r"CONTA:\s*(\d[\d-]*)",
        fim_da_tabela=r"^CENTRAL DE SUPORTE",
        # o Safra não tem coluna de saldo e lista os saldos (inclusive de aplicação) como linhas
        conferir_saldo=False,
    ),
    Layout(
        nome="Santander", codigo_banco="0033",
        identificacao=r"SANTANDER",
        colunas=[Coluna("Data", DATA), Coluna("Histórico", HISTORICO, centralizada=True),
                 Coluna("Documento", CONCATENAR), Coluna("Valor", VALOR), Coluna("Saldo", SALDO)],
        conta=r"Conta:\s*(\d+)",
        fim_da_tabela=r"^A - SALDO",
    ),
]


def identificar_layout(nome_arquivo: str, texto: str) -> Optional[Layout]:
    # Primeiro pelo nome do arquivo, depois pelo conteúdo (um histórico pode citar outro banco)
    for alvo in (sem_acentos(nome_arquivo), sem_acentos(texto)):
        if layout := next((l for l in LAYOUTS if re.search(l.identificacao, alvo)), None):
            return layout
    return None


# ---------------------------------------------------------------------------
# Localização das colunas
# ---------------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", sem_acentos(texto))


@dataclass
class _Faixa:
    papel: str
    numerica: bool
    x0: float           # início do cabeçalho
    x1: float           # fim do cabeçalho
    inicio: float = 0   # a partir de qual X uma palavra de texto pertence a esta coluna


def _localizar_cabecalho(linha: Linha, layout: Layout) -> Optional[list[_Faixa]]:
    """Se a linha for o cabeçalho da tabela, devolve a faixa X de cada coluna."""
    palavras = sorted(linha, key=lambda p: p[0])
    normalizadas = [_normalizar(p[4]) for p in palavras]
    faixas, pos = [], 0
    for coluna in layout.colunas:
        encontrada = None
        for alternativa in coluna.cabecalho.split("|"):
            alvo = [_normalizar(t) for t in alternativa.split() if _normalizar(t)]
            for i in range(pos, len(palavras) - len(alvo) + 1):
                if normalizadas[i:i + len(alvo)] == alvo:
                    encontrada = (i, i + len(alvo))
                    break
            if encontrada:
                break
        if not encontrada:
            return None
        inicio, fim = encontrada
        faixas.append(_Faixa(coluna.papel, coluna.numerica or coluna.papel in COLUNAS_DE_VALOR,
                             palavras[inicio][0], palavras[fim - 1][2]))
        pos = fim

    tolerancia = 2 * LARGURA_CARACTERE
    for i, (faixa, coluna) in enumerate(zip(faixas, layout.colunas)):
        if i == 0:
            faixa.inicio = float("-inf")
        elif coluna.centralizada:
            faixa.inicio = (faixas[i - 1].x1 + faixa.x0) / 2
        else:
            faixa.inicio = faixa.x0 - tolerancia
    return faixas


def _juntar_sufixo_c_d(palavras: Linha) -> Linha:
    """Caixa e BB escrevem "2,00 D": junta o sufixo C/D ao valor."""
    palavras = sorted(palavras, key=lambda p: (round(p[3]), p[0]))
    resultado: Linha = []
    for p in palavras:
        anterior = resultado[-1] if resultado else None
        if (anterior and p[4] in ("C", "D") and RE_DINHEIRO.fullmatch(anterior[4])
                and abs(anterior[3] - p[3]) < 3 and p[0] - anterior[2] < 2 * LARGURA_CARACTERE):
            resultado[-1] = (anterior[0], anterior[1], p[2], anterior[3], f"{anterior[4]} {p[4]}", *anterior[5:])
        else:
            resultado.append(p)
    return resultado


def _distribuir(linha: Linha, faixas: list[_Faixa]) -> dict[str, list[str]]:
    """Distribui as palavras da linha nas colunas.

    Valores monetários são alinhados à direita ou centralizados: vão para a coluna
    numérica mais próxima. Textos são alinhados à esquerda: vão para a última coluna cuja
    faixa começa antes da palavra. A coluna de data só aceita datas: um texto que cai nela
    (histórico que começa à esquerda do cabeçalho) vai para a coluna seguinte.
    """
    faixas_numericas = [f for f in faixas if f.numerica] or faixas
    celulas: dict[int, list[tuple]] = {}
    for p in _juntar_sufixo_c_d(linha):
        if RE_DINHEIRO.fullmatch(p[4].split()[0]):
            centro = (p[0] + p[2]) / 2
            faixa = min(faixas_numericas, key=lambda f: abs((f.x0 + f.x1) / 2 - centro))
        else:
            indice = len([f for f in faixas if f.inicio <= p[0]]) - 1
            if faixas[indice].papel == DATA and not RE_DATA.fullmatch(p[4]) and indice + 1 < len(faixas):
                indice += 1
            faixa = faixas[indice]
        celulas.setdefault(id(faixa), []).append(p)

    resultado: dict[str, list[str]] = {}
    for faixa in faixas:
        palavras = celulas.get(id(faixa), [])
        if palavras:
            texto = " ".join(p[4] for p in sorted(palavras, key=lambda p: (round(p[3]), p[0])))
            resultado.setdefault(faixa.papel, []).append(texto)
    return resultado


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

@dataclass
class ResultadoLayout:
    conta: Optional[str]
    lancamentos: list[Lancamento] = field(default_factory=list)
    saldo_anterior: Optional[float] = None
    saldo_final: Optional[float] = None
    nao_listadas: list[MovimentacaoNaoListada] = field(default_factory=list)


def extrair_com_layout(paginas: list[list[Linha]], layout: Layout, texto: str, ano: Optional[str]) -> ResultadoLayout:
    resultado = ResultadoLayout(conta=_extrair_conta(layout, texto))

    faixas: Optional[list[_Faixa]] = None
    na_tabela = False
    lancamentos_liberados = layout.inicio_dos_lancamentos is None
    ultima_data: Optional[str] = None
    ultimo_saldo: Optional[float] = None
    # Controle de movimentações não listadas (pontos de controle de saldo)
    saldo_corrido: Optional[float] = None
    datas_vistas: list[str] = []
    datas_com_aplicacao: set[str] = set()

    for pagina in paginas:
        for linha in pagina:
            texto_linha = sem_acentos(renderizar(linha)).strip()

            if layout.inicio_dos_lancamentos and re.search(layout.inicio_dos_lancamentos, texto_linha):
                lancamentos_liberados = True
                continue
            if (novas_faixas := _localizar_cabecalho(linha, layout)) is not None:
                faixas, na_tabela = novas_faixas, True
                continue
            if layout.fim_da_tabela and re.search(layout.fim_da_tabela, texto_linha):
                na_tabela = False
                continue
            if not na_tabela or faixas is None:
                continue

            celulas = _distribuir(linha, faixas)
            datas = RE_DATA.findall(" ".join(celulas.get(DATA, [])))
            if datas:
                ultima_data = normalizar_data(datas[0], ano)

            historico = " ".join(celulas.get(HISTORICO, []) + celulas.get(CONCATENAR, []))
            historico = " ".join(historico.split())

            saldo = parse_saldo(celulas[SALDO][-1]) if SALDO in celulas else None
            valor, operacao = _valor_e_operacao(celulas, layout)

            if ultima_data and (not datas_vistas or datas_vistas[-1] != ultima_data):
                datas_vistas.append(ultima_data)
            if layout.aplicacao_automatica and re.search(layout.aplicacao_automatica, sem_acentos(historico)):
                datas_com_aplicacao.add(ultima_data)

            # Ponto de controle: o banco informa o saldo da conta; a diferença para o saldo
            # corrido é movimentação que não aparece como lançamento
            if (layout.saldo_da_conta and saldo is not None
                    and re.search(layout.saldo_da_conta, sem_acentos(historico))):
                if saldo_corrido is not None and abs(saldo - saldo_corrido) >= 0.01:
                    resultado.nao_listadas.append(
                        _movimentacao_nao_listada(saldo - saldo_corrido, ultima_data, datas_vistas, datas_com_aplicacao))
                saldo_corrido = saldo

            if valor is None:
                if saldo is not None:
                    ultimo_saldo = saldo
                # Linha sem valor: complemento do histórico do lançamento anterior (BB)
                if (layout.anexar_linhas_sem_valor and lancamentos_liberados and resultado.lancamentos
                        and historico and not datas):
                    anterior = resultado.lancamentos[-1]
                    # a linha inteira: o complemento pode avançar sobre a coluna vizinha
                    anterior.historico = f"{anterior.historico} {' '.join(renderizar(linha).split())}"
                continue

            # Linhas de saldo e valores zerados não são lançamentos
            if eh_linha_de_saldo(historico) or valor == 0 or not lancamentos_liberados:
                if saldo is None and eh_linha_de_saldo(historico) and layout.conferir_saldo:
                    saldo = parse_saldo(celulas[VALOR][-1]) if VALOR in celulas else None
            else:
                if not resultado.lancamentos:
                    resultado.saldo_anterior = ultimo_saldo
                resultado.lancamentos.append(Lancamento(
                    data=ultima_data, historico=historico, operacao=operacao, valor=valor))
                if saldo_corrido is not None:
                    saldo_corrido += valor if operacao == "credito" else -valor

            if saldo is not None:
                ultimo_saldo = saldo

    if layout.conferir_saldo:
        if not resultado.lancamentos:
            resultado.saldo_anterior = ultimo_saldo
        resultado.saldo_final = ultimo_saldo
    return resultado


def _movimentacao_nao_listada(diferenca: float, data: Optional[str], datas_vistas: list[str],
                              datas_com_aplicacao: set[str]) -> MovimentacaoNaoListada:
    """Classifica a diferença entre o saldo corrido e o saldo informado pelo banco.

    Só é considerada explicada se houver aplicação automática no mesmo dia ou no dia
    anterior (o resgate costuma acontecer no dia seguinte à aplicação). Caso contrário,
    pode ser um lançamento que o parser não leu, e a conferência não passa.
    """
    indice = datas_vistas.index(data) if data in datas_vistas else -1
    dias_relevantes = {data} | ({datas_vistas[indice - 1]} if indice > 0 else set())
    explicada = bool(dias_relevantes & datas_com_aplicacao)

    if not explicada:
        descricao = "Movimentação não identificada"
    elif diferenca < 0:
        descricao = "Aplicação automática (não listada pelo banco)"
    else:
        descricao = "Resgate automático (não listado pelo banco)"
    return MovimentacaoNaoListada(data=data, valor=round(diferenca, 2), descricao=descricao, explicada=explicada)


def _valor_e_operacao(celulas: dict[str, list[str]], layout: Layout) -> tuple[Optional[float], Optional[str]]:
    for papel in (VALOR, CREDITO, DEBITO):
        if papel not in celulas:
            continue
        valor, operacao = parse_valor(celulas[papel][0])
        if valor is None:
            continue
        # Prioridade: sinal/sufixo C-D do valor > coluna (Bradesco) > padrão do layout > positivo = crédito
        operacao = (operacao
                    or {CREDITO: "credito", DEBITO: "debito"}.get(papel)
                    or layout.operacao_padrao
                    or "credito")
        return valor, operacao
    return None, None


def _extrair_conta(layout: Layout, texto: str) -> Optional[str]:
    if match := re.search(layout.conta, texto):
        conta = next(g for g in match.groups() if g)
        # Caixa: "XXXX | XXXX | XXXXXXXXXX-X" -> a conta é o último item
        return conta.split("|")[-1].strip()
    return None
