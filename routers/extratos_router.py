from email.errors import HeaderParseError
from email.header import decode_header, make_header

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from httpx import ConnectError

from schemas.extrato import ExtratoConta
from security.security import verify_token
from services.transcribe_service import transcrever_uploads

router = APIRouter()

TAMANHO_MAXIMO = 20 * 1024 * 1024  # 20 MB por arquivo


def _nome_do_arquivo(arquivo: UploadFile) -> str:
    """Nome original do arquivo.

    O .NET Framework (PowerShell 5.1 do Windows Server) envia nomes com acento no formato
    RFC 2047, ex.: "=?utf-8?B?RXh0cmF0by...?=". Aqui volta a ser "Extrato conciliação.pdf".
    """
    nome = arquivo.filename or "sem_nome.pdf"
    try:
        return str(make_header(decode_header(nome)))
    except (HeaderParseError, UnicodeDecodeError, LookupError):
        return nome


def _ler_pdf(arquivo: UploadFile) -> bytes:
    conteudo = arquivo.file.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"{arquivo.filename}: arquivo maior que {TAMANHO_MAXIMO // (1024 * 1024)} MB.")
    # Confere pelo conteúdo, não pela extensão: todo PDF começa com "%PDF-"
    if not conteudo.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{arquivo.filename}: o arquivo não é um PDF.")
    return conteudo


# "def" (e não "async def"): a extração é síncrona/bloqueante, assim o FastAPI roda em uma threadpool
@router.post("/extratos", response_model=dict[str, list[ExtratoConta]], status_code=status.HTTP_200_OK,
             dependencies=[Depends(verify_token)])
def enviar_extratos(arquivos: list[UploadFile] = File(..., description="Um ou mais extratos em PDF.")):
    pdfs = [(_nome_do_arquivo(arquivo), _ler_pdf(arquivo)) for arquivo in arquivos]
    try:
        return transcrever_uploads(pdfs)
    except (ConnectionError, ConnectError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Não foi possível conectar ao Ollama.")
