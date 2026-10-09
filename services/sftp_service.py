"""Busca dos extratos no servidor do cliente via SFTP.

Configuração (.env):
    SFTP_HOST, SFTP_PORTA (22), SFTP_USUARIO
    SFTP_SENHA ou SFTP_CHAVE (caminho da chave privada; preferível à senha)
    SFTP_PASTA_BASE      pasta raiz dos extratos no servidor do cliente (ex.: "/D:/A PAGAR/AEROFLEX")
    SFTP_KNOWN_HOSTS     arquivo known_hosts com a chave do servidor (obrigatório: sem ele não conecta)

Todos os caminhos recebidos pela API são RELATIVOS à SFTP_PASTA_BASE e não podem sair dela.

Para gerar a linha do known_hosts (confira a impressão digital com o TI do cliente):
    python -m services.sftp_service known-hosts <host> [porta]
"""
from __future__ import annotations

import io
import os
import posixpath
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import paramiko

TAMANHO_MAXIMO = 20 * 1024 * 1024  # 20 MB por arquivo, igual ao upload
TIMEOUT = 20  # segundos para conectar/autenticar


class ErroSftp(Exception):
    """Falha ao falar com o SFTP do cliente (conexão, autenticação, chave do servidor)."""


class SftpNaoConfigurado(ErroSftp):
    pass


class CaminhoInvalido(ValueError):
    """Caminho absoluto ou com "..": tentaria sair da pasta base."""


class NaoEncontrado(FileNotFoundError):
    pass


@dataclass(frozen=True)
class ConfigSftp:
    host: str
    porta: int
    usuario: str
    senha: str | None
    chave: str | None
    pasta_base: str
    known_hosts: str


def carregar_config() -> ConfigSftp:
    from services import credenciais

    def env(nome: str, padrao: str | None = None) -> str | None:
        return credenciais.obter(nome) or padrao   # .env/variável de ambiente ou Gerenciador de Credenciais

    faltando = [nome for nome in ("SFTP_HOST", "SFTP_USUARIO", "SFTP_PASTA_BASE", "SFTP_KNOWN_HOSTS") if not env(nome)]
    if not env("SFTP_SENHA") and not env("SFTP_CHAVE"):
        faltando.append("SFTP_SENHA ou SFTP_CHAVE")
    if faltando:
        raise SftpNaoConfigurado(f"SFTP não configurado. Faltando no .env: {', '.join(faltando)}.")
    if not os.path.isfile(env("SFTP_KNOWN_HOSTS")):
        raise SftpNaoConfigurado(f"Arquivo SFTP_KNOWN_HOSTS não encontrado: {env('SFTP_KNOWN_HOSTS')}")
    return ConfigSftp(
        host=env("SFTP_HOST"),
        porta=int(env("SFTP_PORTA", "22")),
        usuario=env("SFTP_USUARIO"),
        senha=env("SFTP_SENHA") or None,
        chave=env("SFTP_CHAVE") or None,
        pasta_base=env("SFTP_PASTA_BASE").rstrip("/") or "/",
        known_hosts=env("SFTP_KNOWN_HOSTS"),
    )


def caminho_remoto(pasta_base: str, relativo: str) -> str:
    """Junta o caminho relativo à pasta base, recusando qualquer tentativa de sair dela."""
    relativo = (relativo or "").replace("\\", "/").strip()
    if relativo.startswith("/") or (len(relativo) > 1 and relativo[1] == ":"):
        raise CaminhoInvalido(f"Use caminho relativo à pasta base, não absoluto: {relativo}")
    partes = [p for p in relativo.split("/") if p not in ("", ".")]
    if ".." in partes:
        raise CaminhoInvalido(f"Caminho não pode conter '..': {relativo}")
    return posixpath.join(pasta_base, *partes) if partes else pasta_base


def _nome_known_hosts(host: str, porta: int) -> str:
    """Formato da chave do host no arquivo known_hosts (igual ao de linha_known_hosts)."""
    return host if porta == 22 else f"[{host}]:{porta}"


@contextmanager
def conectar(config: ConfigSftp | None = None) -> Iterator[paramiko.SFTPClient]:
    config = config or carregar_config()
    ssh = paramiko.SSHClient()
    ssh.load_host_keys(config.known_hosts)
    # Servidor com chave desconhecida ou diferente da registrada: recusa (proteção contra servidor falso)
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    if not ssh.get_host_keys().lookup(_nome_known_hosts(config.host, config.porta)):
        raise ErroSftp(f"Servidor {config.host} não está no known_hosts ({config.known_hosts}).")
    try:
        ssh.connect(config.host, port=config.porta, username=config.usuario,
                    password=config.senha, key_filename=config.chave,
                    look_for_keys=False, allow_agent=False,
                    timeout=TIMEOUT, banner_timeout=TIMEOUT, auth_timeout=TIMEOUT)
        sftp = ssh.open_sftp()
    except paramiko.BadHostKeyException as erro:
        ssh.close()
        raise ErroSftp(f"A chave do servidor SFTP mudou ({config.host}). Confira com o TI do cliente "
                       f"antes de atualizar o known_hosts.") from erro
    except paramiko.AuthenticationException as erro:
        ssh.close()
        raise ErroSftp(f"Usuário ou senha/chave do SFTP recusados por {config.host}.") from erro
    except paramiko.SSHException as erro:
        ssh.close()
        raise ErroSftp(f"Falha no SSH com {config.host}: {erro}") from erro
    except (TimeoutError, OSError) as erro:
        ssh.close()
        raise ErroSftp(f"Sem conexão com o SFTP {config.host}:{config.porta} ({erro}).") from erro
    try:
        yield sftp
    finally:
        sftp.close()
        ssh.close()


def listar(sftp: paramiko.SFTPClient, caminho: str) -> tuple[list[str], list[str]]:
    """(subpastas, PDFs) de um caminho remoto absoluto, em ordem alfabética."""
    try:
        itens = sftp.listdir_attr(caminho)
    except FileNotFoundError as erro:
        raise NaoEncontrado(caminho) from erro
    pastas = sorted(i.filename for i in itens if stat.S_ISDIR(i.st_mode or 0))
    pdfs = sorted(i.filename for i in itens
                  if stat.S_ISREG(i.st_mode or 0) and i.filename.lower().endswith(".pdf"))
    return pastas, pdfs


def baixar(sftp: paramiko.SFTPClient, caminho: str) -> bytes:
    """Conteúdo de um arquivo remoto, em memória (nada é gravado em disco)."""
    try:
        tamanho = sftp.stat(caminho).st_size or 0
    except FileNotFoundError as erro:
        raise NaoEncontrado(caminho) from erro
    if tamanho > TAMANHO_MAXIMO:
        raise ValueError(f"arquivo maior que {TAMANHO_MAXIMO // (1024 * 1024)} MB")
    buffer = io.BytesIO()
    sftp.getfo(caminho, buffer)
    return buffer.getvalue()


def linha_known_hosts(host: str, porta: int = 22) -> tuple[str, str]:
    """Lê a chave pública do servidor: (linha para o known_hosts, impressão digital SHA256)."""
    with paramiko.Transport((host, porta)) as transporte:
        transporte.start_client(timeout=TIMEOUT)
        chave = transporte.get_remote_server_key()
    nome = host if porta == 22 else f"[{host}]:{porta}"
    return f"{nome} {chave.get_name()} {chave.get_base64()}", chave.fingerprint


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "known-hosts":
        print(__doc__)
        sys.exit(1)
    linha, impressao = linha_known_hosts(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 22)
    print(f"# Impressão digital: {impressao}  (confirme com o TI do cliente)", file=sys.stderr)
    print(linha)
