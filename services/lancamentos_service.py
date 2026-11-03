"""Lançamentos do dia (POST /lancamentos e /lancamentos/sftp): lê os extratos e aplica as regras da AEROFLEX.

Mesmo caminho do robô: escolhe os PDFs da pasta do dia (pasta do dia útil seguinte ao movimento, Safra ATUALIZADO
pela data do nome), lê cada um com os layouts desta API, classifica as linhas (config/regras.yaml) e monta o plano.
"""
from __future__ import annotations

import posixpath
from datetime import date
from pathlib import PurePath, PurePosixPath
from typing import Optional

from lancamentos.cadastro import Cadastro, cadastro_padrao, feriados as ler_feriados
from lancamentos.integracao import plano_para_integracao
from lancamentos.leitura import ler_resposta_api
from lancamentos.pastas import dia_util_anterior, dia_util_seguinte, listar_extratos, pasta_do_dia
from lancamentos.planejamento import planejar
from schemas.extrato import ExtratoConta
from services import credenciais, sftp_service
from services.sftp_service import NaoEncontrado


class SemExtratos(FileNotFoundError):
    """A pasta do dia ainda não tem extratos."""


def feriados_configurados() -> frozenset[date]:
    return ler_feriados(credenciais.obter("FERIADOS"))


def movimento_padrao(feriados: frozenset[date]) -> date:
    """Sem data informada: o dia útil anterior a hoje (como o robô)."""
    return dia_util_anterior(date.today(), feriados)


def lancamentos(resposta: dict[str, list[ExtratoConta]], data_movimento: date,
                feriados: frozenset[date] = frozenset(), cadastro: Optional[Cadastro] = None) -> dict:
    """Extratos já lidos -> plano do dia em JSON (lancamentos, pendencias, fora_do_escopo, extratos)."""
    cadastro = cadastro or cadastro_padrao()
    bruto = {banco: [e.model_dump() for e in lista] for banco, lista in resposta.items()}
    plano = planejar(ler_resposta_api(bruto, cadastro), cadastro, data_movimento, feriados)
    return plano_para_integracao(plano, cadastro.constantes)


class FonteSftp:
    """Pastas do SFTP do cliente vistas pelas regras de lancamentos.pastas (caminhos relativos à pasta base)."""

    def __init__(self, sftp, pasta_base: str):
        self.sftp, self.pasta_base = sftp, pasta_base

    def _listar(self, pasta: PurePath) -> Optional[tuple[list[str], list[str]]]:
        try:
            return sftp_service.listar(self.sftp, sftp_service.caminho_remoto(self.pasta_base, str(pasta)))
        except NaoEncontrado:
            return None

    def subpastas(self, pasta: PurePath) -> Optional[list[str]]:
        listagem = self._listar(pasta)
        return sorted(listagem[0]) if listagem is not None else None

    def pdfs(self, pasta: PurePath) -> list[str]:
        listagem = self._listar(pasta)
        return sorted(listagem[1]) if listagem is not None else []


def arquivos_do_dia(fonte, data_movimento: date, feriados: frozenset[date],
                    cadastro: Optional[Cadastro] = None) -> list[PurePosixPath]:
    """PDFs do movimento: pasta do dia útil seguinte + Safra ATUALIZADO (mesma regra do robô)."""
    cadastro = cadastro or cadastro_padrao()
    raiz = PurePosixPath(".")
    pasta_dia = pasta_do_dia(raiz, dia_util_seguinte(data_movimento, feriados), fonte)
    pasta_movimento = pasta_do_dia(raiz, data_movimento, fonte)
    arquivos = listar_extratos(pasta_dia, pasta_movimento, cadastro, fonte, data_movimento)
    if not arquivos:
        raise SemExtratos(f"Nenhum PDF na pasta {pasta_dia} do SFTP (extratos do movimento de "
                          f"{data_movimento:%d/%m/%Y}).")
    return arquivos


def lancamentos_do_sftp(data_movimento: date, feriados: frozenset[date], ler_um) -> dict:
    """`ler_um(sftp, relativo, remoto)` lê um PDF do SFTP (o mesmo de POST /extratos/sftp)."""
    from services.transcribe_service import agrupar_por_banco

    config = sftp_service.carregar_config()
    with sftp_service.conectar(config) as sftp:
        arquivos = arquivos_do_dia(FonteSftp(sftp, config.pasta_base), data_movimento, feriados)
        extratos = [ler_um(sftp, posixpath.normpath(str(a)), sftp_service.caminho_remoto(config.pasta_base, str(a)))
                    for a in arquivos]
    return lancamentos(agrupar_por_banco(extratos), data_movimento, feriados)
