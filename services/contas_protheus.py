"""Banco e agência das contas da AEROFLEX como estão no Cadastro de Bancos do Protheus (SA6).

Usado só na resposta do POST /transcribe (integração direta pela API do Protheus). Os valores são os mesmos de
config/contas.yaml do robô (repo irmão); agência exatamente como no cadastro (ex.: Bradesco C/C "06349" e caução "6349").
O extrato não traz a agência num formato único, por isso ela vem desta tabela, pelo número da conta lido do PDF.
"""
from __future__ import annotations

import re

# banco (COMPE, 3 dígitos) -> [(agência no Protheus, trechos de dígitos que identificam a conta no campo "conta" do PDF)]
AGENCIAS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "001": [("3404", ("41000",))],
    "033": [("04296", ("13001842",)),
            ("4296", ("29000181", "29000371", "29000376", "29000432"))],
    "104": [("4266", ("5769805",       # C/C
                      "572845528",     # vinculada, como vem no PDF (4266/1292/000572845528-6)
                      "57845528"))],   # vinculada, como está no Protheus
    "237": [("06349", ("50542",)),
            ("6349", ("3179",))],
    "246": [("0001", ("6609345", "6609348"))],
    "341": [("4685", ("6896", "83117"))],
    "422": [("03800", ("580275", "326613"))],
    "634": [("0001", ("230032",))],
    "707": [("0001", ("1500926", "866622"))],
}


def codigo_banco(chave: str) -> str | None:
    """"banco_0001" -> "001" (código do banco no Protheus); None se o banco não foi identificado."""
    match = re.fullmatch(r"banco_(\d+)", chave)
    return f"{int(match.group(1)):03d}" if match else None


def agencia(banco: str | None, conta: str | None) -> str | None:
    """Agência no Protheus pelo número da conta lido do PDF; None se a conta não é uma das cadastradas."""
    digitos = re.sub(r"\D", "", conta or "")
    if not banco or not digitos:
        return None
    for numero_agencia, trechos in AGENCIAS.get(banco, []):
        if any(trecho in digitos for trecho in trechos):
            return numero_agencia
    return None
