import re
from typing import Union

import pymupdf

# Distância vertical máxima (em pontos) entre as bases de duas palavras para ficarem na mesma linha
TOLERANCIA_Y = 3
# Folga (em pontos) para considerar que uma linha de texto "encosta" verticalmente na linha do valor
TOLERANCIA_SOBREPOSICAO = 1
# Largura aproximada de um caractere, usada para converter distância horizontal em espaços
LARGURA_CARACTERE = 4.5

RE_VALOR = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")

# Palavra: (x0, y0, x1, y1, texto, ...) - mesmo formato do page.get_text("words")
Palavra = tuple
Linha = list[Palavra]


def _palavras(page) -> list[Palavra]:
    """Palavras da página já nas coordenadas da página como ela é exibida.

    Em páginas rotacionadas (ex.: relatório de tarifas do ABC) o get_text("words")
    devolve as coordenadas sem rotação, o que embaralha as linhas.
    """
    palavras = page.get_text("words")
    if not page.rotation:
        return palavras
    matriz = page.rotation_matrix
    return [(*pymupdf.Rect(p[:4]).transform(matriz), *p[4:]) for p in palavras]


def _agrupar_em_linhas(palavras: list[Palavra]) -> list[Linha]:
    palavras = sorted(palavras, key=lambda p: (round(p[3]), p[0]))
    linhas: list[Linha] = []
    for palavra in palavras:
        if linhas and abs(linhas[-1][0][3] - palavra[3]) <= TOLERANCIA_Y:
            linhas[-1].append(palavra)
        else:
            linhas.append([palavra])
    return linhas


def _texto(linha: Linha) -> str:
    return " ".join(p[4] for p in sorted(linha, key=lambda p: p[0]))


def _y0(linha):
    return min(p[1] for p in linha)


def _y1(linha):
    return max(p[3] for p in linha)


def _juntar_celulas_quebradas(linhas: list[Linha]) -> list[Linha]:
    """Junta à linha do lançamento as linhas de texto que fazem parte da mesma célula.

    Vários bancos (Bradesco, Santander, Itaú) quebram o histórico em 2-3 linhas,
    centralizadas verticalmente em relação à linha que tem o valor. Uma linha SEM valor
    que se sobrepõe verticalmente a uma linha COM valor pertence a ela.
    """
    tem_valor = [bool(RE_VALOR.search(_texto(l))) for l in linhas]
    destino = list(range(len(linhas)))

    for i, linha in enumerate(linhas):
        if tem_valor[i]:
            continue
        for j in (i - 1, i + 1, i - 2, i + 2):
            if 0 <= j < len(linhas) and tem_valor[j]:
                sobrepoe = (_y0(linha) < _y1(linhas[j]) + TOLERANCIA_SOBREPOSICAO
                            and _y0(linhas[j]) < _y1(linha) + TOLERANCIA_SOBREPOSICAO)
                if sobrepoe:
                    destino[i] = j
                    break

    grupos: dict[int, Linha] = {}
    for i, linha in enumerate(linhas):
        grupos.setdefault(destino[i], []).extend(linha)
    return [grupos[k] for k in sorted(grupos)]


def agrupar_celulas(palavras: list[Palavra]) -> list[list[Palavra]]:
    """Agrupa palavras horizontalmente próximas (ou sobrepostas) em células."""
    celulas: list[list[Palavra]] = []
    for palavra in sorted(palavras, key=lambda p: p[0]):
        if celulas and palavra[0] - max(p[2] for p in celulas[-1]) < 2 * LARGURA_CARACTERE:
            celulas[-1].append(palavra)
        else:
            celulas.append([palavra])
    return celulas


def texto_da_celula(celula: list[Palavra]) -> str:
    """Texto de uma célula, lido de cima para baixo e da esquerda para a direita."""
    return " ".join(p[4] for p in sorted(celula, key=lambda p: (round(p[3]), p[0])))


def renderizar(palavras: Linha) -> str:
    """Monta o texto da linha, posicionando cada coluna proporcionalmente à sua coordenada X."""
    texto = ""
    for celula in agrupar_celulas(palavras):
        coluna = int(min(p[0] for p in celula) / LARGURA_CARACTERE)
        espacos = max(2, coluna - len(texto)) if texto else coluna
        texto += " " * espacos + texto_da_celula(celula)
    return texto.rstrip()


def _abrir(origem: Union[str, bytes]):
    """Abre o PDF a partir de um caminho ou do conteúdo em memória (upload)."""
    if isinstance(origem, bytes):
        return pymupdf.open(stream=origem, filetype="pdf")
    return pymupdf.open(origem)


def extrair_linhas(origem: Union[str, bytes]) -> list[list[Linha]]:
    """Para cada página, as linhas visuais (cada uma com suas palavras e coordenadas).

    O get_text() padrão devolve cada célula da tabela em uma linha separada, o que
    "desmonta" as linhas do extrato. Aqui cada lançamento volta a ser uma linha.
    """
    with _abrir(origem) as doc:
        return [_juntar_celulas_quebradas(_agrupar_em_linhas(_palavras(page))) for page in doc]


def extrair_paginas(origem: Union[str, bytes]) -> list[str]:
    """Extrai o texto de cada página do PDF preservando o layout das linhas."""
    return ["\n".join(renderizar(linha) for linha in pagina) for pagina in extrair_linhas(origem)]
