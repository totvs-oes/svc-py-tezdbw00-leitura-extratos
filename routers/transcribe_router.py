from fastapi import APIRouter, Depends, Query, status

from llm.erros import ErroIA, erro_ia_para_http
from schemas.extrato import ExtratoContaComOpcao
from security.security import verify_token
from services.transcribe_service import transcrever

router = APIRouter()


@router.post("/transcribe", response_model=dict[str, list[ExtratoContaComOpcao]], status_code=status.HTTP_200_OK,
             dependencies=[Depends(verify_token)])
def transcribe_pdf(
    arquivo: str | None = Query(None, description="Filtra os PDFs de teste pelo nome (ex.: ABC, SAFRA)."),
):
    """Só teste: lê os PDFs fixos de docs_example/ (filtro opcional pelo nome do arquivo).
    Cada lançamento traz `opcao`/`descricao_opcao` da Movimentação Bancária do Protheus (3 = a Pagar, 4 = a Receber)."""
    try:
        resultado = transcrever(arquivo)
    except ErroIA as erro:
        raise erro_ia_para_http(erro)
    return {banco: [ExtratoContaComOpcao.de(e) for e in extratos] for banco, extratos in resultado.items()}
