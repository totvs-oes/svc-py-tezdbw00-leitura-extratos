import posixpath

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from llm.erros import ErroIA
from schemas.extrato import ExtratoConta
from security.security import verify_token
from services import sftp_service
from services.sftp_service import (
    CaminhoInvalido,
    ErroSftp,
    NaoEncontrado,
    SftpNaoConfigurado,
)
from services.transcribe_service import agrupar_por_banco, sem_leitura, transcrever_pdf

router = APIRouter(dependencies=[Depends(verify_token)])


class Listagem(BaseModel):
    caminho: str = Field(description="Caminho relativo à pasta base do SFTP.")
    pastas: list[str]
    arquivos: list[str] = Field(description="Somente PDFs.")


class PedidoSftp(BaseModel):
    arquivos: list[str] = Field(min_length=1, max_length=200,
                                description="Caminhos dos PDFs, relativos à pasta base do SFTP "
                                            '(ex.: "2026 AEROFLEX/09 - SETEMBRO/10-09/BRADESCO 3179-8 10-09.pdf").')


def _erro_http(erro: Exception) -> HTTPException:
    if isinstance(erro, CaminhoInvalido):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
    if isinstance(erro, SftpNaoConfigurado):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(erro))
    # Conexão, autenticação ou chave do servidor: o problema está no SFTP do cliente
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(erro))

@router.get("/sftp/listar", response_model=Listagem)
def listar(caminho: str = Query("", description="Pasta relativa à pasta base (vazio = a própria base).")):
    """Lista subpastas e PDFs de uma pasta do SFTP do cliente."""
    try:
        config = sftp_service.carregar_config()
        remoto = sftp_service.caminho_remoto(config.pasta_base, caminho)
        with sftp_service.conectar(config) as sftp:
            pastas, arquivos = sftp_service.listar(sftp, remoto)
    except NaoEncontrado:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Pasta não encontrada no SFTP: {caminho}")
    except (CaminhoInvalido, ErroSftp) as erro:
        raise _erro_http(erro)
    return Listagem(caminho=caminho, pastas=pastas, arquivos=arquivos)


@router.post("/extratos/sftp", response_model=dict[str, list[ExtratoConta]])
def ler_do_sftp(pedido: PedidoSftp):
    """Baixa os PDFs do SFTP do cliente e lê cada um.

    Um arquivo com problema (não encontrado, não é PDF, IA fora do ar...) volta como extrato com
    metodo "nenhum" e aviso, sem derrubar os outros. Só falhas do próprio SFTP viram erro HTTP.
    """
    try:
        config = sftp_service.carregar_config()
        remotos = [(relativo, sftp_service.caminho_remoto(config.pasta_base, relativo)) for relativo in pedido.arquivos]
        extratos = []
        with sftp_service.conectar(config) as sftp:
            for relativo, remoto in remotos:
                extratos.append(_ler_um(sftp, relativo, remoto))
    except (CaminhoInvalido, ErroSftp) as erro:
        raise _erro_http(erro)
    return agrupar_por_banco(extratos)


def _ler_um(sftp, relativo: str, remoto: str):
    nome = posixpath.basename(remoto)
    try:
        conteudo = sftp_service.baixar(sftp, remoto)
    except NaoEncontrado:
        return sem_leitura(nome, f"Arquivo não encontrado no SFTP: {relativo}")
    except ValueError as erro:
        return sem_leitura(nome, f"Arquivo rejeitado: {erro}")
    if not conteudo.startswith(b"%PDF-"):
        return sem_leitura(nome, "O arquivo não é um PDF.")
    try:
        return transcrever_pdf(nome, conteudo)
    except ErroIA as erro:
        return sem_leitura(nome, f"Layout desconhecido e a IA não está disponível ({erro}): arquivo não lido.")
