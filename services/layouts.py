"""Layouts conhecidos de extrato: um parser determinístico por banco.

Cada layout descreve as colunas da tabela de lançamentos pelo texto do cabeçalho.
A posição X de cada cabeçalho no PDF define a "faixa" da coluna, e cada palavra
de uma linha vai para a coluna em que cai. Não há IA envolvida: o resultado é exato
e instantâneo. PDFs que não casam com nenhum layout caem no fallback com IA.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from schemas.extrato import Lancamento, MovimentacaoNaoListada
from services.normalizacao import (
    eh_linha_de_saldo,
    normalizar_data,
    parse_saldo,
    parse_valor,
    sem_acentos,
)
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
    fim_da_tabela: str | None = None  # regex da linha que encerra a tabela
    inicio_dos_lancamentos: str | None = None  # só considera lançamentos após essa linha
    operacao_padrao: str | None = None         # ex.: relatório de tarifas é sempre débito
    anexar_linhas_sem_valor: bool = False         # BB: complemento do histórico vem na linha de baixo
    conferir_saldo: bool = True
    # Linhas que informam o saldo da conta corrente ao longo do extrato (pontos de controle).
    # Se o saldo corrido divergir delas, há movimentação que o banco não listou.
    saldo_da_conta: str | None = None
    # Históricos que indicam aplicação automática (justificam a movimentação não listada)
    aplicacao_automatica: str | None = None
    # Extrato sem tabela de colunas (ex.: Daycoval): parser próprio no lugar do de colunas
    parser: Callable[[list[list[Linha]], "Layout", str, str | None], "ResultadoLayout"] | None = None
    # Regex removida do início do histórico (ex.: ABC novo: nº do documento sem coluna própria)
    prefixo_do_historico: str | None = None
    # Regex (um grupo) do saldo anterior quando ele vem fora da tabela (ex.: Caixa vinculada)
    saldo_anterior_no_texto: str | None = None
    # Regex de linhas da tabela que não são lançamento nem saldo da conta (ex.: Tribanco "SALDO VINCULADO/BLOQUEADO")
    ignorar_linhas: str | None = None


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
    # ABC "Extrato detalhado" (visto em 11/09 e 16/09/2026): "Nro. Documento" no lugar de "Quantidade" e
    # "Saldo diário"; pode cobrir mais de um dia (ex.: 10/09 a 11/09) e o débito vem com sinal ("-726.387,29").
    # Sem coluna para o "Nro. Documento": na conta corrente o "Nro." vem numa linha acima do cabeçalho.
    Layout(
        nome="ABC", codigo_banco="0246",
        identificacao=r"BANCO ABC|ABC BRASIL",
        colunas=[Coluna("Data", DATA), Coluna("Histórico", HISTORICO),
                 Coluna("Operação", IGNORAR), Coluna("Valor (R$)", VALOR), Coluna("Saldo diário", SALDO)],
        conta=r"Conta:\s*(\d+)|\b(00\d{8})\b",
        fim_da_tabela=r"^CANAL:|^OS SALDOS",
        prefixo_do_historico=r"^(\d{7}|-)\s+",
    ),
    # Tribanco (Banco Triângulo), "REL. DE EXTRATO PERIÓDICO PARA CORRENTISTA" (visto em 11-09): valor com D/C e o
    # saldo na última coluna; cada dia traz SALDO DISPONIVEL/VINCULADO/BLOQUEADO: só o disponível é o saldo da conta.
    Layout(
        nome="Tribanco", codigo_banco="0634",
        identificacao=r"TRIBANCO|BANCO TRIANGULO",
        colunas=[Coluna("Data.", DATA), Coluna("Descrição", HISTORICO), Coluna("Doc", IGNORAR, centralizada=True),
                 Coluna("Valor D/C", VALOR), Coluna("Valor", SALDO)],
        conta=r"\b(\d{7}-\d)\b",
        fim_da_tabela=r"^PAGINA \d",
        ignorar_linhas=r"SALDO (VINCULADO|BLOQUEADO)",
    ),
    # Caixa conta vinculada ("CAIXA VINCULADA.pdf", visto em 11-09): mês até a data, valores com sufixo C/D e o
    # saldo anterior numa frase acima da tabela. Testado antes do "Caixa" (cabeçalhos diferentes).
    Layout(
        nome="Caixa vinculada", codigo_banco="0104",
        identificacao=r"CAIXA",
        colunas=[Coluna("Data/Hora", DATA), Coluna("Nr. Doc.", CONCATENAR), Coluna("Descrição/Detalhamento", HISTORICO),
                 Coluna("Valor (R$)", VALOR), Coluna("Saldo(R$)", SALDO)],
        conta=r"Conta:\s*([\d/-]+)",
        fim_da_tabela=r"^SAC CAIXA",
        saldo_anterior_no_texto=r"SALDO ANTERIOR A \d{2}/\d{2}/\d{4}\s+R\$\s*([\d.]+,\d{2}\s*[CD])",
    ),
    Layout(
        nome="Caixa", codigo_banco="0104",
        identificacao=r"CAIXA",
        colunas=[Coluna("Data Mov.", DATA), Coluna("Nr. Doc.", CONCATENAR), Coluna("Histórico", HISTORICO),
                 Coluna("Valor", VALOR), Coluna("Saldo", SALDO)],
        conta=r"Conta:\s*([^\n]+)",
        # Lê o período inteiro + "Lançamentos do Dia" (mesmo saldo corrido). Só o "do Dia" (dia da emissão)
        # deixava de fora o dia do movimento: o PDF da pasta 11-09 não trazia as tarifas de 10/09 (visto 08/10/2026).
        fim_da_tabela=r"^SAC CAIXA",
    ),
    Layout(
        nome="Tarifas BB", codigo_banco="0001",
        identificacao=r"^TARIFAS (BB|BANCO DO BRASIL)\b|CONSULTA MOVIMENTO DO DIA",
        colunas=[],
        conta=r"Benefici\w+\s+(\d{4,6}-[\dX])\b",
        conferir_saldo=False,
        parser=lambda paginas, layout, texto, ano: extrair_tarifas_bb(paginas, layout, texto, ano),
    ),
    Layout(
        nome="Banco do Brasil", codigo_banco="0001",
        identificacao=r"BANCO DO BRASIL|BB CASH",
        colunas=[Coluna("Dt. balancete", DATA), Coluna("Ag. origem", IGNORAR), Coluna("Lote", IGNORAR),
                 Coluna("Histórico", HISTORICO), Coluna("Documento", IGNORAR, centralizada=True),
                 Coluna("Valor R$", VALOR), Coluna("Saldo", SALDO)],
        conta=r"Conta corrente\s+(\d[\d-]*)",
        fim_da_tabela=r"^LANCAMENTOS FUTUROS|LIMITE ESPECIAL DA CONTA",   # 16-09: sem "Lançamentos futuros"; vem o limite
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
        # Relatório "Movimentação de Títulos" da carteira de cobrança: detalha a linha "TAR/CUSTAS COBRANCA"
        # do extrato da conta corrente, tarifa por boleto. Antes do "Itaú": o nome "TARIFAS ITAU" casa com os dois.
        nome="Tarifas Itaú", codigo_banco="0341",
        identificacao=r"TARIFAS ITAU|MOVIMENTACAO DE TITULOS",
        colunas=[],
        conta=r"(\d{4}/\d{5}-\d)",
        parser=lambda paginas, layout, texto, ano: extrair_tarifas_itau(paginas, layout, texto, ano),
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
    Layout(
        nome="Daycoval", codigo_banco="0707",
        identificacao=r"DAYCOVAL|DAYCONNECT",
        colunas=[],  # sem tabela: cada lançamento é uma linha "dd/mm HISTÓRICO COMPLEMENTO  [-]R$ valor"
        conta=r"Conta Corrente\s*\n\s*(\d[\d-]*)",
        parser=lambda paginas, layout, texto, ano: extrair_daycoval(paginas, layout, texto, ano),
    ),
]


def identificar_layout(nome_arquivo: str, zona: str, paginas: list[list[Linha]] | None = None) -> Layout | None:
    """Layout do extrato, ou None (vai para a IA).

    Candidatos: pelo nome do arquivo, depois pela zona de identificação (cabeçalho/rodapés, ver
    normalizacao.zona_de_identificacao). Um candidato só vale se o cabeçalho da tabela dele existir
    no PDF: sem essa confirmação, um layout errado devolveria zero lançamentos sem avisar.
    """
    candidatos: list[Layout] = []
    for alvo in (sem_acentos(nome_arquivo), sem_acentos(zona)):
        candidatos += [l for l in LAYOUTS if re.search(l.identificacao, alvo) and l not in candidatos]
    return next((l for l in candidatos if paginas is None or _confirmado(l, paginas)), None)


def _confirmado(layout: Layout, paginas: list[list[Linha]]) -> bool:
    if layout.parser:  # sem tabela de colunas (Daycoval): vale a identificação
        return True
    paginas = _separar_cabecalho_grudado(paginas, layout)
    return any(_localizar_cabecalho(linha, layout) is not None for pagina in paginas for linha in pagina)


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


def _separar_cabecalho_grudado(paginas: list[list[Linha]], layout: Layout) -> list[list[Linha]]:
    """A junção de células quebradas (pdf_service) às vezes gruda a 1ª linha da tabela no cabeçalho (BB de 16/09/2026:
    "Dt. 14/09/2026 balancete ..."); ordenadas por X, as palavras se intercalam e o cabeçalho não é reconhecido.
    Separa essa linha em duas pela altura: cabeçalho e linha de lançamento."""
    resultado = []
    for pagina in paginas:
        nova: list[Linha] = []
        for linha in pagina:
            if _localizar_cabecalho(linha, layout) is None:
                alturas = sorted({round(p[3]) for p in linha})
                grupos = [[p for p in linha if abs(round(p[3]) - y) <= 1] for y in alturas]
                cabecalho = next((g for g in grupos if len(g) < len(linha) and _localizar_cabecalho(g, layout)), None)
                if cabecalho:
                    nova += [cabecalho, [p for p in linha if p not in cabecalho]]
                    continue
            nova.append(linha)
        resultado.append(nova)
    return resultado


def _separar_cabecalho_grudado(paginas: list[list[Linha]], layout: Layout) -> list[list[Linha]]:
    """A junção de células quebradas (pdf_service) às vezes gruda a 1ª linha da tabela no cabeçalho (BB de 16/09/2026:
    "Dt. 14/09/2026 balancete ..."); ordenadas por X, as palavras se intercalam e o cabeçalho não é reconhecido.
    Separa essa linha em duas pela altura: cabeçalho e linha de lançamento."""
    resultado = []
    for pagina in paginas:
        nova: list[Linha] = []
        for linha in pagina:
            if _localizar_cabecalho(linha, layout) is None:
                alturas = sorted({round(p[3]) for p in linha})
                grupos = [[p for p in linha if abs(round(p[3]) - y) <= 1] for y in alturas]
                cabecalho = next((g for g in grupos if len(g) < len(linha) and _localizar_cabecalho(g, layout)), None)
                if cabecalho:
                    nova += [cabecalho, [p for p in linha if p not in cabecalho]]
                    continue
            nova.append(linha)
        resultado.append(nova)
    return resultado


def _localizar_cabecalho(linha: Linha, layout: Layout) -> list[_Faixa] | None:
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
    conta: str | None
    lancamentos: list[Lancamento] = field(default_factory=list)
    saldo_anterior: float | None = None
    saldo_final: float | None = None
    nao_listadas: list[MovimentacaoNaoListada] = field(default_factory=list)


def extrair_com_layout(paginas: list[list[Linha]], layout: Layout, texto: str, ano: str | None) -> ResultadoLayout:
    if layout.parser:
        return layout.parser(paginas, layout, texto, ano)
    resultado = ResultadoLayout(conta=_extrair_conta(layout, texto))
    paginas = _separar_cabecalho_grudado(paginas, layout)

    faixas: list[_Faixa] | None = None
    na_tabela = False
    lancamentos_liberados = layout.inicio_dos_lancamentos is None
    ultima_data: str | None = None
    ultimo_saldo: float | None = None
    # Controle de movimentações não listadas (pontos de controle de saldo)
    saldo_corrido: float | None = None
    datas_vistas: list[str] = []
    datas_com_aplicacao: set[str] = set()

    for pagina in paginas:
        for linha in pagina:
            texto_linha = sem_acentos(renderizar(linha)).strip()
            if layout.ignorar_linhas and re.search(layout.ignorar_linhas, texto_linha):
                continue

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
            if layout.prefixo_do_historico:
                historico = re.sub(layout.prefixo_do_historico, "", historico, count=1)

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
        if layout.saldo_anterior_no_texto and (m := re.search(layout.saldo_anterior_no_texto, sem_acentos(texto))):
            resultado.saldo_anterior = parse_saldo(m.group(1))
    return resultado


def _movimentacao_nao_listada(diferenca: float, data: str | None, datas_vistas: list[str],
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


def _valor_e_operacao(celulas: dict[str, list[str]], layout: Layout) -> tuple[float | None, str | None]:
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


def _extrair_conta(layout: Layout, texto: str) -> str | None:
    if match := re.search(layout.conta, texto):
        conta = next(g for g in match.groups() if g)
        # Caixa: "XXXX | XXXX | XXXXXXXXXX-X" -> a conta é o último item
        return conta.split("|")[-1].strip()
    return None


# ---------------------------------------------------------------------------
# Daycoval (Dayconnect): extrato em blocos, sem cabeçalho de colunas
# ---------------------------------------------------------------------------
#
#   Saldo anterior                                   R$ 304.965,75
#   Saldo atual                                      R$ 320.049,70
#   Quinta-feira, 03 de setembro                     Saldo: R$ 320.049,70   <- saldo do fim do dia (não usado)
#   03/09 TRANSF.MESMA TITULARIDADE   8666220 - ...  R$ 100.691,20          <- crédito (sem sinal)
#   01/09 TARIFA DE MANUTENCAO DE C/C 9232818        -R$ 43,79              <- débito
#
# Os dias vêm do mais recente para o mais antigo; a saída fica em ordem cronológica, como nos outros bancos.

RE_DAYCOVAL_VALOR = re.compile(r"-?R\$\s*[\d.]+,\d{2}")
RE_DAYCOVAL_LANCAMENTO = re.compile(r"^(\d{2}/\d{2})\s+(.+?)\s+(-?R\$\s*[\d.]+,\d{2})$")
RE_DAYCOVAL_PERIODO = re.compile(r"(\d{2}/\d{2}/\d{4})\s+A\s+(\d{2}/\d{2}/\d{4})")


def _ano_no_periodo(data_curta: str, periodo: tuple[str, str] | None, ano: str | None) -> str | None:
    """Ano do lançamento "dd/mm". Período que vira o ano (29/12 a 04/01): mês maior que o final = ano inicial."""
    if not periodo:
        return ano
    inicio, fim = periodo
    return inicio[6:] if int(data_curta[3:5]) > int(fim[3:5]) else fim[6:]


def extrair_daycoval(paginas: list[list[Linha]], layout: Layout, texto: str, ano: str | None) -> ResultadoLayout:
    resultado = ResultadoLayout(conta=_extrair_conta(layout, texto))
    periodo = RE_DAYCOVAL_PERIODO.search(sem_acentos(texto))
    periodo = periodo.groups() if periodo else None

    lancamentos: list[Lancamento] = []
    for pagina in paginas:
        for linha in pagina:
            texto_linha = " ".join(renderizar(linha).split())
            normalizada = sem_acentos(texto_linha)
            valor_da_linha = RE_DAYCOVAL_VALOR.search(texto_linha)
            # O sinal vem antes do "R$" ("-R$ 43,79"): só o trecho do valor vai para o parse
            if normalizada.startswith("SALDO ANTERIOR ") and valor_da_linha:
                resultado.saldo_anterior = parse_saldo(valor_da_linha.group())
            elif normalizada.startswith("SALDO ATUAL ") and valor_da_linha:
                resultado.saldo_final = parse_saldo(valor_da_linha.group())
            elif match := RE_DAYCOVAL_LANCAMENTO.match(texto_linha):
                data_curta, historico, texto_valor = match.groups()
                valor, operacao = parse_valor(texto_valor)
                if not valor:
                    continue
                lancamentos.append(Lancamento(
                    data=normalizar_data(data_curta, _ano_no_periodo(data_curta, periodo, ano)),
                    historico=historico, operacao=operacao or "credito", valor=valor))

    # A conferência (saldo anterior + lançamentos = saldo atual) pega lançamento que ficou de fora
    resultado.lancamentos = list(reversed(lancamentos))
    return resultado


# ---------------------------------------------------------------------------
# Tarifas Itaú: relatório "Movimentação de Títulos" (detalhe da linha TAR/CUSTAS COBRANCA do extrato)
# ---------------------------------------------------------------------------
#
#   Cart. Nosso nº/Dac Seu nº  Nome do pagador  Dep./Rec. Vencimento  Valor     Hist. Dia/mês Cód. Outros Valores Crédito/Débito
#   109   00129495-8  0000714702 W. L. MAGAZINE  4320      03/08/26   1.005,92  L     09/09   04   62,16
#                                                                                             01   0,89            1.067,19+
#   109   00077345-7  0000540419 51115238 RAFAEL 9893      05/11/24   857,08    TM    09/09                         1,79 -
#   ...
#   Resumo das Deduções:  Tarifa - 0,00 +  Custas 342,76 -  Total Deduções 342,76 -
#
# Tarifas: código 01 (tarifa de cobrança, valor em "Outros Valores") e históricos T? (TM = manutenção de título
# vencido; TN, TQ...; valor em "Crédito/Débito"). Código 04 (juros) e 05 (desconto) não são tarifas. Cada tarifa vira um lançamento.
# Conferência: a soma das tarifas tem que dar o "Total Deduções" do resumo, ao centavo.
#
# As palavras são reagrupadas pela altura real na página: a junção de células quebradas do pdf_service gruda a
# primeira linha de cada página no cabeçalho, e a tarifa dela se perderia.

RE_TARIFAS_ITAU_CARTEIRA = re.compile(r"\d{3}")            # 109, 157... (10/09/2026 trouxe a carteira 157)
RE_TARIFAS_ITAU_NOSSO_NUMERO = re.compile(r"\d{6,9}-?\d?")  # "00129495-8" (09/09) ou "001307990" (10/09)
RE_TARIFAS_ITAU_EMISSAO = re.compile(r"(\d{2}/\d{2}/\d{2,4})")
TOLERANCIA_COLUNA = 20  # pt: distância máxima entre a palavra e o X do cabeçalho ("09/09" fica 15 pt depois de "Dia/mês")


def _linhas_visuais(pagina: list[Linha]) -> list[list[tuple]]:
    palavras = sorted((p for linha in pagina for p in linha), key=lambda p: (round(p[3]), p[0]))
    linhas: list[list[tuple]] = []
    for p in palavras:
        if linhas and abs(linhas[-1][0][3] - p[3]) <= 2:
            linhas[-1].append(p)
        else:
            linhas.append([p])
    return [sorted(l, key=lambda p: p[0]) for l in linhas]


def _colunas_tarifas_itau(linhas: list[list[tuple]]) -> dict[str, float] | None:
    for linha in linhas:
        x = {sem_acentos(p[4]).rstrip("."): p[0] for p in linha}
        if {"COD", "OUTROS", "CREDITO/DEBITO", "HIST", "DIA/MES"} <= x.keys():
            return {"hist": x["HIST"], "dia": x["DIA/MES"], "cod": x["COD"], "outros": x["OUTROS"],
                    "cd": x["CREDITO/DEBITO"]}
    return None


def extrair_tarifas_itau(paginas: list[list[Linha]], layout: Layout, texto: str, ano: str | None) -> ResultadoLayout:
    resultado = ResultadoLayout(conta=_extrair_conta(layout, texto))
    normalizado = sem_acentos(texto)
    emissao = re.search(r"EMITIDO EM.*?" + RE_TARIFAS_ITAU_EMISSAO.pattern, normalizado, re.DOTALL)
    ano_relatorio = ano
    if emissao:
        dia_emissao = emissao.group(1)
        ano_relatorio = dia_emissao[-4:] if len(dia_emissao) == 10 else "20" + dia_emissao[-2:]

    colunas: dict[str, float] | None = None
    titulo = ""            # "<nosso nº> <pagador>" do boleto da linha atual (a linha do 01 pode vir sozinha)
    dia_mes: str | None = None
    fora_do_agrupado = 0.0  # tarifas de negativação (TN/TQ/TC): o extrato debita em linhas próprias
    for pagina in paginas:
        linhas = _linhas_visuais(pagina)
        colunas = _colunas_tarifas_itau(linhas) or colunas
        if colunas is None:
            continue

        def na_coluna(p, coluna: str) -> bool:
            return abs(p[0] - colunas[coluna]) <= TOLERANCIA_COLUNA

        for linha in linhas:
            if (len(linha) > 2 and RE_TARIFAS_ITAU_CARTEIRA.fullmatch(linha[0][4])
                    and RE_TARIFAS_ITAU_NOSSO_NUMERO.fullmatch(linha[1][4])):  # linha de boleto: carteira + nosso nº
                pagador = [p[4] for p in linha if colunas["hist"] - 380 < p[0] < colunas["hist"] - 180
                           and not RE_DINHEIRO.fullmatch(p[4]) and not RE_DATA.fullmatch(p[4]) and not p[4].isdigit()]
                titulo = f"{linha[1][4]} {' '.join(pagador)}".strip()
            if dia := next((p[4] for p in linha if na_coluna(p, "dia") and RE_DATA.fullmatch(p[4])), None):
                dia_mes = dia
            historico = next((p[4] for p in linha if na_coluna(p, "hist") and p[4].isalpha()), "")
            data = normalizar_data(dia_mes, ano_relatorio) if dia_mes else None

            # Código 01 = tarifa de cobrança: valor na coluna "Outros Valores"
            if any(p[4] == "01" and na_coluna(p, "cod") for p in linha):
                valor = next((p for p in linha if RE_DINHEIRO.fullmatch(p[4])
                              and colunas["outros"] - 30 <= p[0] < colunas["cd"] - 20), None)
                if valor and (v := parse_valor(valor[4])[0]):
                    resultado.lancamentos.append(Lancamento(
                        data=data, historico=f"TAR COBRANCA {titulo}", operacao="debito", valor=v))
            # Históricos "T?" com valor (débito) na coluna "Crédito/Débito":
            #   TM = manutenção de título vencido -> compõe a linha TAR/CUSTAS do extrato: vira lançamento;
            #   TN/TQ/TC = negativação (entrada/liquidação/cancelamento, 13,25 e 15,65 em 11 e 15/09/2026) -> o
            #   extrato já debita em linhas próprias ("TAR NEGAT ENT/LIQ/CAN"), lançadas como tarifa comum: só entram
            #   na conferência com o "Total Deduções". Código novo que não seja tarifa aparece na conferência.
            elif len(historico) == 2 and historico.startswith("T"):
                valor = next((p for p in linha if RE_DINHEIRO.fullmatch(p[4]) and p[0] >= colunas["cd"] - 20), None)
                if valor and (v := parse_valor(valor[4])[0]):
                    if historico == "TM":
                        resultado.lancamentos.append(Lancamento(
                            data=data, historico=f"TAR MANUT TIT VENCIDO {titulo}", operacao="debito", valor=v))
                    else:
                        fora_do_agrupado += v

    # Conferência: tarifas lidas + as debitadas à parte = "Total Deduções" do resumo
    # (saldo_anterior - débitos = saldo_final 0)
    if (total := _total_deducoes_itau(paginas)) is not None:
        resultado.saldo_anterior = round(total - fora_do_agrupado, 2)
        resultado.saldo_final = 0.0
    return resultado


# ---------------------------------------------------------------------------
# Tarifas BB: "Consulta movimento do dia" (detalhe da linha "Débito Serviço Cobrança Tar. agrupadas" do extrato)
# ---------------------------------------------------------------------------
#
#   Data do movimento 11/09/2026        Títulos - Instrucoes Diversas      (um PDF por tipo: Baixado, Registrado...)
#   Nosso nro.  Nome do Sacado  Vencto. Dt.oper Vl.título Tarifa Acrésc. Desc Op. Vl.líquido Nº beneficiário
#   16022480003143306-  MARINHO E TRAPP
#                       03/09/2026 11/09/2026 1.259,91  6,87  0,00   TEC  0,00  000126264
#   3                   ARMARINHOS LTDA
#
# Cada título com "Tarifa" > 0 vira um lançamento (RGP registro, BX baixa, TEC instrução...). Linha DCA (cartório)
# vem com tarifa 0,00 e fica de fora. Não há total no relatório: quem confere é o robô (soma dos relatórios do dia ==
# tarifa agrupada do extrato; validado em 09/09, 11/09 e 14/09/2026).

RE_TARIFAS_BB_NOSSO_NUMERO = re.compile(r"\d{15,20}-?")
RE_TARIFAS_BB_DATA_MOVIMENTO = re.compile(r"DATA DO MOVIMENTO\s+(\d{2}/\d{2}/\d{4})")


def extrair_tarifas_bb(paginas: list[list[Linha]], layout: Layout, texto: str, ano: str | None) -> ResultadoLayout:
    resultado = ResultadoLayout(conta=_extrair_conta(layout, texto))
    movimento = RE_TARIFAS_BB_DATA_MOVIMENTO.search(sem_acentos(texto))
    data = movimento.group(1) if movimento else None
    x_tarifa = x_op = None
    nosso, sacado = "", []
    for pagina in paginas:
        for linha in _linhas_visuais(pagina):
            for p in linha:
                if p[4] == "Tarifa":
                    x_tarifa = p[0]
                elif p[4] == "Op.":
                    x_op = p[0]
            if x_tarifa is None:
                continue
            if RE_TARIFAS_BB_NOSSO_NUMERO.fullmatch(linha[0][4]):  # linha do título: nosso nº + início do sacado
                nosso = linha[0][4].rstrip("-")
                sacado = [p[4] for p in linha[1:] if p[0] < x_tarifa - 100]
                continue
            valor = next((p for p in linha if abs(p[0] - x_tarifa) <= 15 and RE_DINHEIRO.fullmatch(p[4])), None)
            if valor and (v := parse_valor(valor[4])[0]):
                op = next((p[4] for p in linha if x_op is not None and abs(p[0] - x_op) <= 15 and p[4].isalpha()), "")
                historico = " ".join(["TAR COBRANCA BB", op, nosso] + sacado)
                resultado.lancamentos.append(Lancamento(data=data, historico=" ".join(historico.split()),
                                                        operacao="debito", valor=v))
    return resultado


def _total_deducoes_itau(paginas: list[list[Linha]]) -> float | None:
    """Valor sob o rótulo "Total Deduções": o mais à direita da linha seguinte ao cabeçalho do resumo.

    Pela posição, não pela ordem do texto: em 10/09/2026 o resumo trouxe "Custas 0,00" na mesma linha e a ordem do
    texto mudou; o valor continua na coluna do rótulo (ex.: rótulo em x=692, valor em x=740).
    """
    for pagina in paginas:
        linhas = _linhas_visuais(pagina)
        for i, linha in enumerate(linhas[:-1]):
            textos = [sem_acentos(p[4]).upper() for p in linha]
            for j in range(len(textos) - 1):
                if textos[j] == "TOTAL" and textos[j + 1].startswith("DEDU"):
                    x_rotulo = linha[j][0]
                    valores = [p for p in linhas[i + 1] if p[0] >= x_rotulo and RE_DINHEIRO.fullmatch(p[4])]
                    if valores:
                        return parse_valor(max(valores, key=lambda p: p[0])[4])[0]
    return None

