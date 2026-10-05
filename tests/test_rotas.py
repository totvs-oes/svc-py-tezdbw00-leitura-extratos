"""Rotas HTTP: token, validação do upload e proteções do SFTP (sem servidor SFTP real)."""
import pytest
from fastapi.testclient import TestClient

from main import app
from services import sftp_service
from services.sftp_service import CaminhoInvalido, SftpNaoConfigurado, caminho_remoto

TOKEN = "token-de-teste"
CABECALHO = {"Authorization": f"Bearer {TOKEN}"}
SFTP_VARS = ("SFTP_HOST", "SFTP_PORTA", "SFTP_USUARIO", "SFTP_SENHA", "SFTP_CHAVE", "SFTP_PASTA_BASE", "SFTP_KNOWN_HOSTS")


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("TOKEN", TOKEN)
    for nome in SFTP_VARS:  # o .env de quem roda os testes não pode influenciar
        monkeypatch.delenv(nome, raising=False)
    return TestClient(app)


@pytest.mark.parametrize("metodo, rota, kwargs", [
    ("post", "/extratos", {"files": {"arquivos": ("a.pdf", b"%PDF-1.4", "application/pdf")}}),
    ("get", "/sftp/listar", {}),
    ("post", "/extratos/sftp", {"json": {"arquivos": ["a.pdf"]}}),
])
def test_rotas_exigem_token(cliente, metodo, rota, kwargs):
    assert getattr(cliente, metodo)(rota, **kwargs).status_code == 401
    assert getattr(cliente, metodo)(rota, headers={"Authorization": "Bearer errado"}, **kwargs).status_code == 401


def test_upload_que_nao_e_pdf_recusado(cliente):
    resposta = cliente.post("/extratos", headers=CABECALHO,
                            files={"arquivos": ("extrato.pdf", b"isto nao e um pdf", "application/pdf")})
    assert resposta.status_code == 400 and "não é um PDF" in resposta.json()["detail"]


def test_sftp_nao_configurado_responde_503(cliente):
    resposta = cliente.get("/sftp/listar", headers=CABECALHO)
    assert resposta.status_code == 503 and "SFTP_HOST" in resposta.json()["detail"]


def test_sftp_known_hosts_inexistente(monkeypatch, tmp_path):
    for nome, valor in {"SFTP_HOST": "h", "SFTP_USUARIO": "u", "SFTP_SENHA": "s", "SFTP_PASTA_BASE": "/base",
                        "SFTP_KNOWN_HOSTS": str(tmp_path / "nao_existe")}.items():
        monkeypatch.setenv(nome, valor)
    with pytest.raises(SftpNaoConfigurado, match="KNOWN_HOSTS"):
        sftp_service.carregar_config()


@pytest.mark.parametrize("relativo, esperado", [
    ("", "/D:/A PAGAR/AEROFLEX"),
    ("2026 AEROFLEX/09 - SETEMBRO/10-09", "/D:/A PAGAR/AEROFLEX/2026 AEROFLEX/09 - SETEMBRO/10-09"),
    ("2026 AEROFLEX\\09 - SETEMBRO\\10-09\\ITAU 6896-9 10-09.pdf",
     "/D:/A PAGAR/AEROFLEX/2026 AEROFLEX/09 - SETEMBRO/10-09/ITAU 6896-9 10-09.pdf"),
    ("./pasta//sub/", "/D:/A PAGAR/AEROFLEX/pasta/sub"),
])
def test_caminho_relativo_fica_dentro_da_pasta_base(relativo, esperado):
    assert caminho_remoto("/D:/A PAGAR/AEROFLEX", relativo) == esperado


@pytest.mark.parametrize("relativo", ["../segredo", "pasta/../../etc", "/etc/passwd", "C:/Windows", "D:\\outra"])
def test_caminho_que_sai_da_pasta_base_e_recusado(relativo):
    with pytest.raises(CaminhoInvalido):
        caminho_remoto("/D:/A PAGAR/AEROFLEX", relativo)


def test_rota_sftp_recusa_caminho_invalido_com_400(cliente, monkeypatch, tmp_path):
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("")
    for nome, valor in {"SFTP_HOST": "h", "SFTP_USUARIO": "u", "SFTP_SENHA": "s", "SFTP_PASTA_BASE": "/base",
                        "SFTP_KNOWN_HOSTS": str(known_hosts)}.items():
        monkeypatch.setenv(nome, valor)
    resposta = cliente.get("/sftp/listar", params={"caminho": "../fora"}, headers=CABECALHO)
    assert resposta.status_code == 400  # recusado antes de qualquer conexão
