import re
import unicodedata

# Código COMPE -> palavras que identificam o banco no texto do PDF ou no nome do arquivo
BANCOS = {
    "0001": ["BANCO DO BRASIL", "BB CASH"],
    "0033": ["SANTANDER"],
    "0104": ["CAIXA"],
    "0237": ["BRADESCO"],
    "0246": ["ABC BRASIL", "BANCO ABC", "ABC "],
    "0260": ["NUBANK", "NU PAGAMENTOS"],
    "0336": ["C6 BANK", "BANCO C6"],
    "0341": ["ITAU"],
    "0422": ["SAFRA"],
    "0707": ["DAYCOVAL", "DAYCONNECT"],
}

RE_VALOR = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}")
RE_DATA_COMPLETA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
RE_DATA_CURTA = re.compile(r"^(\d{2})/(\d{2})$")
RE_DATA_MES_ESCRITO = re.compile(r"^(\d{1,2})\s+(?:DE\s+)?([A-Z]{3,9})\.?(?:\s+(?:DE\s+)?(\d{4}))?$")
MESES_ABREVIADOS = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
# Linhas de saldo que a LLM às vezes deixa passar. "SALDO VINCULADO LIBERADO" é movimentação real.
RE_SALDO = re.compile(r"^(S\s?A\s?L\s?D\s?O)\b(?!\s+VINCULADO)")


def sem_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper()


def zona_de_identificacao(paginas: list[str], linhas_topo: int = 8, linhas_rodape: int = 6) -> str:
    """Cabeçalho da 1ª página + rodapé de cada página: onde o extrato diz de que banco é.

    O corpo fica de fora de propósito: nele aparecem os bancos das CONTRAPARTES
    (ex.: "Transferência Pix ... CAIXA ECONOMICA FEDERAL (0104) Agência: ..." num extrato do Nubank).
    """
    trechos = []
    for numero, pagina in enumerate(paginas):
        linhas = [l for l in pagina.splitlines() if l.strip()]
        if numero == 0:
            trechos += linhas[:linhas_topo]
        trechos += linhas[-linhas_rodape:]
    return "\n".join(trechos)


def identificar_banco(zona: str, nome_arquivo: str) -> str | None:
    """Identifica o banco de forma determinística: nome do arquivo primeiro, depois a zona de identificação.

    Passe a zona_de_identificacao(), não o texto inteiro: o corpo cita os bancos das contrapartes.
    """
    for fonte in (sem_acentos(nome_arquivo), sem_acentos(zona)):
        for codigo, termos in BANCOS.items():
            if any(termo in fonte for termo in termos):
                return codigo
    return None


def parse_valor(texto: str | None) -> tuple[float | None, str | None]:
    """Converte "1.234,56 D" / "-12,11" / "68.875,15 C" em (valor absoluto, operação indicada pelo texto).

    A operação só é retornada quando o próprio texto deixa explícito (sinal ou sufixo C/D).
    """
    if not texto:
        return None, None
    t = texto.upper().replace("R$", "").strip()
    match = RE_VALOR.search(t)
    if not match:
        return None, None
    valor = float(match.group().replace(".", "").replace(",", "."))

    if t.startswith("-") or t.endswith(("-", "D")):
        return valor, "debito"
    if t.startswith("+") or t.endswith(("+", "C")):
        return valor, "credito"
    return valor, None


def parse_saldo(texto: str | None) -> float | None:
    valor, operacao = parse_valor(texto)
    if valor is None:
        return None
    return -valor if operacao == "debito" else valor


def ano_do_extrato(texto: str) -> str | None:
    match = RE_DATA_COMPLETA.search(texto)
    return match.group(3) if match else None


def normalizar_data(data: str | None, ano: str | None) -> str | None:
    """Padroniza a data para dd/mm/aaaa (alguns bancos, como o Safra, mostram só dd/mm)."""
    if not data:
        return None
    data = data.strip()
    if match := RE_DATA_COMPLETA.search(data):
        return match.group(0)
    if (match := RE_DATA_CURTA.match(data)) and ano:
        return f"{match.group(1)}/{match.group(2)}/{ano}"
    # Mês por extenso/abreviado (Nubank: "02 SET 2026")
    if match := RE_DATA_MES_ESCRITO.match(sem_acentos(data)):
        dia, mes, ano_data = match.groups()
        ano_data = ano_data or ano
        if mes[:3] in MESES_ABREVIADOS and ano_data:
            return f"{int(dia):02d}/{MESES_ABREVIADOS.index(mes[:3]) + 1:02d}/{ano_data}"
    return data


def eh_linha_de_saldo(historico: str) -> bool:
    return bool(RE_SALDO.match(sem_acentos(historico).strip()))
