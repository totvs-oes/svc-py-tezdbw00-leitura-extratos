"""Contas (config/contas.yaml) e regras de classificação (config/regras.yaml) do Protheus da AEROFLEX.

Mesma estrutura e mesmos arquivos do robô (repo irmão bot-py-tezdbw00-conciliacao-bancaria): enquanto ele existir,
uma regra nova precisa entrar nos dois.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from lancamentos.modelos import Banco, Conta, TipoConta

RAIZ = Path(__file__).resolve().parent.parent
PASTA_CONFIG = RAIZ / "config"


@dataclass(frozen=True)
class Regra:
    nome: str
    categoria: str
    historico: re.Pattern
    operacao: Optional[str] = None
    tipos_conta: Optional[tuple[str, ...]] = None
    bancos: Optional[tuple[str, ...]] = None
    contas: Optional[tuple[str, ...]] = None   # chaves de conta (ex.: só a caução central do Santander)
    destino_tipo: Optional[str] = None
    origem_tipo: Optional[tuple[str, ...]] = None
    origem_conta: Optional[str] = None
    historico_protheus: Optional[str] = None
    natureza: Optional[str] = None   # (tarifa) natureza própria; sem ela vale constantes.natureza_tarifa
    motivo: Optional[str] = None   # (acao_manual) texto da pendência
    acao: Optional[str] = None


@dataclass
class Cadastro:
    """Contas, bancos, regras e constantes do Protheus (vindos de config/*.yaml)."""
    bancos: dict[str, Banco]
    contas: list[Conta]
    regras: list[Regra]
    constantes: dict

    def conta(self, chave: str) -> Conta:
        for conta in self.contas:
            if conta.chave == chave:
                return conta
        raise KeyError(f"Conta '{chave}' não existe em config/contas.yaml")

    def contas_do_banco(self, banco: str, tipo: str) -> list[Conta]:
        return [c for c in self.contas if c.banco == banco and c.tipo.value == tipo]


def _tupla(valor) -> Optional[tuple[str, ...]]:
    if valor is None:
        return None
    if isinstance(valor, (list, tuple)):
        return tuple(str(v) for v in valor)
    return (str(valor),)


def _compilar(historico) -> re.Pattern:
    padrao = "|".join(f"(?:{p})" for p in historico) if isinstance(historico, list) else historico
    return re.compile(padrao)


def carregar_cadastro(pasta: Path = PASTA_CONFIG) -> Cadastro:
    with open(pasta / "contas.yaml", encoding="utf-8") as f:
        dados_contas = yaml.safe_load(f)
    with open(pasta / "regras.yaml", encoding="utf-8") as f:
        dados_regras = yaml.safe_load(f)

    bancos = {codigo: Banco(codigo=codigo, **dados) for codigo, dados in dados_contas["bancos"].items()}
    contas = [Conta(**{**c, "tipo": TipoConta(c["tipo"])}) for c in dados_contas["contas"]]

    chaves = [c.chave for c in contas]
    if len(chaves) != len(set(chaves)):
        raise ValueError("config/contas.yaml tem chaves de conta repetidas")

    regras = [
        Regra(
            nome=r["nome"],
            categoria=r["categoria"],
            historico=_compilar(r["historico"]),
            operacao=r.get("operacao"),
            tipos_conta=_tupla(r.get("tipos_conta")),
            bancos=_tupla(r.get("bancos")),
            contas=_tupla(r.get("contas")),
            destino_tipo=r.get("destino_tipo"),
            origem_tipo=_tupla(r.get("origem_tipo")),
            origem_conta=r.get("origem_conta"),
            historico_protheus=r.get("historico_protheus"),
            natureza=str(r["natureza"]) if r.get("natureza") else None,
            motivo=r.get("motivo"),
            acao=r.get("acao"),
        )
        for r in dados_regras["regras"]
    ]
    return Cadastro(bancos=bancos, contas=contas, regras=regras, constantes=dados_regras["constantes"])


@lru_cache(maxsize=1)
def cadastro_padrao() -> Cadastro:
    """Cadastro de config/ (carregado uma vez por processo; reinicie a API depois de mudar os YAML)."""
    return carregar_cadastro()


def feriados(texto: str) -> frozenset[date]:
    """FERIADOS do .env/Gerenciador de Credenciais: "2026-10-12,2026-11-02"."""
    return frozenset(date.fromisoformat(d.strip()) for d in texto.split(",") if d.strip())
