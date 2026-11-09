from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from routers.sftp_router import _erro_http, _ler_um
from security.security import verify_token
from services.lancamentos_service import (
    PastaNaoConfigurada,
    SemExtratos,
    feriados_configurados,
    lancamentos_da_pasta,
    lancamentos_do_sftp,
    movimento_padrao,
)
from services.sftp_service import CaminhoInvalido, ErroSftp

router = APIRouter(dependencies=[Depends(verify_token)])

DESCRICAO_RESPOSTA = (
    "lancamentos: o que lançar no Protheus (opcao 3 = a Pagar, 4 = a Receber, 7 = Transferência), com natureza, "
    "banco/agência/conta do cadastro e documento. pendencias: linhas que precisam de ação humana (NÃO lançar). "
    "fora_do_escopo: linhas que já entram por outra rotina, ex.: baixa de títulos (NÃO lançar). "
    "baixa_manual: linhas que o financeiro baixa manualmente, só informativo (NÃO lançar). extratos: PDFs lidos.")


class PedidoLancamentos(BaseModel):
    data_movimento: date | None = Field(
        default=None, description="Data dos lançamentos (AAAA-MM-DD). Padrão: dia útil anterior a hoje.")


def _data(pedido: PedidoLancamentos, feriados: frozenset[date]) -> date:
    return pedido.data_movimento or movimento_padrao(feriados)


@router.post("/lancamentos", status_code=status.HTTP_200_OK, response_description=DESCRICAO_RESPOSTA,
             responses={404: {"description": "Pasta do dia sem extratos."},
                        503: {"description": "PASTA_EXTRATOS não configurada ou inacessível."}})
def lancamentos_pasta(pedido: PedidoLancamentos) -> dict:
    """Lançamentos do dia a partir da pasta de extratos (PASTA_EXTRATOS), com as regras da AEROFLEX.

    JSON {"data_movimento": "AAAA-MM-DD"}. Usa a pasta do dia útil seguinte ao movimento (onde a cliente salva os
    extratos) e o Safra ATUALIZADO, como o robô de conciliação."""
    feriados = feriados_configurados()
    try:
        return lancamentos_da_pasta(_data(pedido, feriados), feriados)
    except SemExtratos as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(erro))
    except PastaNaoConfigurada as erro:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(erro))


@router.post("/lancamentos/sftp", status_code=status.HTTP_200_OK, response_description=DESCRICAO_RESPOSTA,
             responses={404: {"description": "Pasta do dia sem extratos."}})
def lancamentos_sftp(pedido: PedidoLancamentos) -> dict:
    """O mesmo de POST /lancamentos, com os extratos do SFTP do cliente."""
    feriados = feriados_configurados()
    try:
        return lancamentos_do_sftp(_data(pedido, feriados), feriados, _ler_um)
    except SemExtratos as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(erro))
    except (CaminhoInvalido, ErroSftp) as erro:
        raise _erro_http(erro)
