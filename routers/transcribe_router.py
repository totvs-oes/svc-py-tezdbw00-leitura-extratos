
from fastapi import APIRouter, Depends, Query, status

from llm.erros import ErroIA, erro_ia_para_http
from schemas.extrato import ExtratoConta
from security.security import verify_token
from services.transcribe_service import transcrever

router = APIRouter()


@router.post("/transcribe", response_model=dict[str, list[ExtratoConta]], status_code=status.HTTP_200_OK,
             dependencies=[Depends(verify_token)])
def transcribe_pdf(
    arquivo: str | None = Query(None, description="Filtra os PDFs de teste pelo nome (ex.: ABC, SAFRA)."),
):
    """Só teste: lê os PDFs fixos de docs_example/ (filtro opcional pelo nome do arquivo)."""
    try:
        return transcrever(arquivo)
    except ErroIA as erro:
        raise erro_ia_para_http(erro)
