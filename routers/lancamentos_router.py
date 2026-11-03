from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from llm.erros import ErroIA, erro_ia_para_http
from routers.extratos_router import _ler_pdf, _nome_do_arquivo
from routers.sftp_router import _erro_http, _ler_um
from security.security import verify_token
from services.lancamentos_service import (
    SemExtratos,
    feriados_configurados,
    lancamentos,
    lancamentos_do_sftp,
    movimento_padrao,
)
from services.sftp_service import CaminhoInvalido, ErroSftp
from services.transcribe_service import transcrever_uploads

router = APIRouter(dependencies=[Depends(verify_token)])

DESCRICAO_RESPOSTA = (
    "lancamentos: o que lançar no Protheus (opcao 3 = a Pagar, 4 = a Receber, 7 = Transferência), com natureza, "
    "banco/agência/conta do cadastro e documento. pendencias: linhas que precisam de ação humana (NÃO lançar). "
    "fora_do_escopo: linhas que já entram por outra rotina, ex.: baixa de títulos (NÃO lançar). extratos: PDFs lidos.")


class PedidoLancamentos(BaseModel):
    data_movimento: date | None = Field(
        default=None, description="Data dos lançamentos (AAAA-MM-DD). Padrão: dia útil anterior a hoje.")


@router.post("/lancamentos/sftp", status_code=status.HTTP_200_OK, response_description=DESCRICAO_RESPOSTA,
             responses={404: {"description": "Pasta do dia sem extratos."}})
def lancamentos_sftp(pedido: PedidoLancamentos) -> dict:
    """Lançamentos do dia a partir dos extratos do SFTP do cliente, com as regras da AEROFLEX.

    Usa a pasta do dia útil seguinte ao movimento (onde a cliente salva os extratos) e o Safra ATUALIZADO,
    como o robô de conciliação."""
    feriados = feriados_configurados()
    data_movimento = pedido.data_movimento or movimento_padrao(feriados)
    try:
        return lancamentos_do_sftp(data_movimento, feriados, _ler_um)
    except SemExtratos as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(erro))
    except (CaminhoInvalido, ErroSftp) as erro:
        raise _erro_http(erro)


@router.post("/lancamentos", status_code=status.HTTP_200_OK, response_description=DESCRICAO_RESPOSTA)
def lancamentos_upload(
    data_movimento: date = Form(..., description="Data dos lançamentos (AAAA-MM-DD)."),
    arquivos: list[UploadFile] = File(..., description="Extratos em PDF do movimento (com os nomes originais)."),
) -> dict:
    """Lançamentos do dia a partir de PDFs enviados por upload. Os nomes dos arquivos identificam as contas
    (config/contas.yaml), como na pasta da cliente."""
    pdfs = [(_nome_do_arquivo(arquivo), _ler_pdf(arquivo)) for arquivo in arquivos]
    try:
        resposta = transcrever_uploads(pdfs)
    except ErroIA as erro:
        raise erro_ia_para_http(erro)
    return lancamentos(resposta, data_movimento, feriados_configurados())
