from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from httpx import ConnectError

from schemas.extrato import ExtratoConta
from security.security import verify_token
from services.transcribe_service import transcrever

router = APIRouter()


@router.post("/transcribe", response_model=dict[str, list[ExtratoConta]], status_code=status.HTTP_200_OK,
             dependencies=[Depends(verify_token)])
def transcribe_pdf(
    arquivo: Optional[str] = Query(None, description="Filtra os PDFs de teste pelo nome (ex.: ABC, SAFRA)."),
):
    try:
        return transcrever(arquivo)
    except (ConnectionError, ConnectError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Não foi possível conectar ao Ollama.")
