import re
import unicodedata
from typing import Optional

# Código COMPE -> palavras que identificam o banco no texto do PDF ou no nome do arquivo
BANCOS = {
    "0001": ["BANCO DO BRASIL", "BB CASH"],
    "0033": ["SANTANDER"],
    "0104": ["CAIXA"],
    "0237": ["BRADESCO"],
    "0246": ["ABC BRASIL", "BANCO ABC", "ABC "],
    "0336": ["C6 BANK", "BANCO C6"],
    "0341": ["ITAU"],
    "0422": ["SAFRA"],
    "0707": ["DAYCOVAL", "DAYCONNECT"],
}

RE_VALOR = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}")
RE_DATA_COMPLETA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
RE_DATA_CURTA = re.compile(r"^(\d{2})/(\d{2})$")
# Linhas de saldo que a LLM às vezes deixa passar. "SALDO VINCULADO LIBERADO" é movimentação real.
RE_SALDO = re.compile(r"^(S\s?A\s?L\s?D\s?O)\b(?!\s+VINCULADO)")


def sem_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper()


def identificar_banco(texto: str, nome_arquivo: str) -> Optional[str]:
    """Identifica o banco de forma determinística (nome do arquivo primeiro, depois o conteúdo)."""
    for fonte in (sem_acentos(nome_arquivo), sem_acentos(texto)):
        for codigo, termos in BANCOS.items():
            if any(termo in fonte for termo in termos):
                return codigo
    return None


def parse_valor(texto: Optional[str]) -> tuple[Optional[float], Optional[str]]:
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

    if t.startswith("-") or t.endswith("-") or t.endswith("D"):
        return valor, "debito"
    if t.startswith("+") or t.endswith("+") or t.endswith("C"):
        return valor, "credito"
    return valor, None


def parse_saldo(texto: Optional[str]) -> Optional[float]:
    valor, operacao = parse_valor(texto)
    if valor is None:
        return None
    return -valor if operacao == "debito" else valor


def ano_do_extrato(texto: str) -> Optional[str]:
    match = RE_DATA_COMPLETA.search(texto)
    return match.group(3) if match else None


def normalizar_data(data: Optional[str], ano: Optional[str]) -> Optional[str]:
    """Padroniza a data para dd/mm/aaaa (alguns bancos, como o Safra, mostram só dd/mm)."""
    if not data:
        return None
    data = data.strip()
    if match := RE_DATA_COMPLETA.search(data):
        return match.group(0)
    if (match := RE_DATA_CURTA.match(data)) and ano:
        return f"{match.group(1)}/{match.group(2)}/{ano}"
    return data


def eh_linha_de_saldo(historico: str) -> bool:
    return bool(RE_SALDO.match(sem_acentos(historico).strip()))
