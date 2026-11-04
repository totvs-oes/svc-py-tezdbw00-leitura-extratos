"""POST /lancamentos e /lancamentos/sftp: o plano do dia pronto para lançar pela API do Protheus."""
import json
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lancamentos.integracao import plano_para_integracao
from lancamentos.planejamento import planejar
from main import app
from routers import lancamentos_router
from schemas.extrato import ExtratoConta
from services import lancamentos_service, sftp_service
from services.sftp_service import NaoEncontrado
from tests.conftest import DIA, FIXTURES

TOKEN = "token-de-teste"
CABECALHO = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("TOKEN", TOKEN)
    monkeypatch.setenv("FERIADOS", "")
    return TestClient(app)


def _resposta_lida() -> dict[str, list[ExtratoConta]]:
    """A mesma leitura de extratos_exemplo.json, como objetos da API."""
    bruto = json.loads((FIXTURES / "extratos_exemplo.json").read_text(encoding="utf-8"))
    return {banco: [ExtratoConta.model_validate(e) for e in lista] for banco, lista in bruto.items()}


# --- JSON de integração -------------------------------------------------------------------------------------------
def test_todo_item_do_plano_vira_um_lancamento(extratos, cadastro):
    plano = planejar(extratos, cadastro, DIA)
    dados = plano_para_integracao(plano, cadastro.constantes)
    assert [l["chave"] for l in dados["lancamentos"]] == [i.chave for i in plano.itens()]
    assert len(dados["lancamentos"]) == 44   # o mesmo número do plano do robô para esses extratos
    assert len(dados["pendencias"]) == len(plano.pendencias)
    assert len(dados["fora_do_escopo"]) == len(plano.fora_do_escopo)
    assert {(l["rotina"], l["opcao"]) for l in dados["lancamentos"]} == {
        ("transferencia", 7), ("tarifa", 3), ("rendimento", 4)}


def test_transferencia_com_contas_do_cadastro_e_constantes(extratos, cadastro):
    dados = plano_para_integracao(planejar(extratos, cadastro, DIA), cadastro.constantes)
    bradesco = [l for l in dados["lancamentos"] if l["opcao"] == 7 and l["valor"] == "51315.72"][0]
    assert bradesco["origem"] == {"banco": "237", "agencia": "6349", "conta": "3179"}
    assert bradesco["destino"] == {"banco": "237", "agencia": "06349", "conta": "0000050542"}
    assert (bradesco["natureza"], bradesco["tipo_mov"], bradesco["filial"]) == ("2001037", "TB", "010101")
    assert bradesco["historico"] == "TRANSF BRAD CAU P/ BRAD C/C"
    assert bradesco["beneficiario"] == "AEROFLEX IND. DE AEROSOL LTDA"


def test_tarifa_e_rendimento(extratos, cadastro):
    dados = plano_para_integracao(planejar(extratos, cadastro, DIA), cadastro.constantes)
    tarifas = [l for l in dados["lancamentos"] if l["rotina"] == "tarifa"]
    assert all(l["natureza"] == "2009028" and l["numerario"] == "M1" for l in tarifas)
    assert [Decimal(l["valor"]) for l in tarifas if l["banco"] == "237"] == [
        Decimal(v) for v in ("90.00", "4.85", "9.70", "2.06", "84.20", "6.93")]
    rendimentos = [l for l in dados["lancamentos"] if l["rotina"] == "rendimento"]
    assert [(l["valor"], l["natureza"], l["historico"], l["beneficiario"]) for l in rendimentos] == [
        ("0.04", "1002002", "REND APLIC", "AEROFLEX"), ("3.55", "1002002", "REND APLIC", "AEROFLEX")]


def test_tarifa_com_natureza_propria(extratos, cadastro):
    plano = planejar(extratos, cadastro, DIA)
    plano.tarifas[0].natureza = "2001054"   # regra tarifa_cambio_bb
    dados = plano_para_integracao(plano, cadastro.constantes)
    assert [l["natureza"] for l in dados["lancamentos"] if l["chave"] == plano.tarifas[0].chave] == ["2001054"]


def test_documento_por_rotina_banco_e_dia_como_o_robo(extratos, cadastro):
    """DDMMAA no primeiro de cada rotina/banco/dia, depois DDMMAA1, DDMMAA2..."""
    dados = plano_para_integracao(planejar(extratos, cadastro, DIA), cadastro.constantes)
    tarifas_bradesco = [l["documento"] for l in dados["lancamentos"] if l["rotina"] == "tarifa" and l["banco"] == "237"]
    assert tarifas_bradesco == ["090926", "0909261", "0909262", "0909263", "0909264", "0909265"]
    rendimentos = [l["documento"] for l in dados["lancamentos"] if l["rotina"] == "rendimento"]
    assert rendimentos == ["090926", "0909261"]


def test_mesma_entrada_mesmo_resultado(extratos, cadastro):
    """Chamar de novo para o mesmo dia devolve as mesmas chaves e documentos (quem lança usa a chave)."""
    primeira = plano_para_integracao(planejar(extratos, cadastro, DIA), cadastro.constantes)
    segunda = plano_para_integracao(planejar(extratos, cadastro, DIA), cadastro.constantes)
    assert primeira == segunda


# --- Rotas -------------------------------------------------------------------------------------------------------
def test_rotas_exigem_token(cliente):
    assert cliente.post("/lancamentos/sftp", json={}).status_code == 401
    assert cliente.post("/lancamentos", json={"data_movimento": "2026-09-09"}).status_code == 401


def _pasta_com_os_extratos_de_exemplo(raiz: Path, monkeypatch) -> list[str]:
    """Pasta da cliente em disco (movimento 09/09 -> pasta 10-09) com um PDF falso por extrato da fixture; a leitura
    de cada PDF devolve o extrato correspondente de extratos_exemplo.json."""
    from services import transcribe_service
    lidos = {e.arquivo: (banco, e) for banco, lista in _resposta_lida().items() for e in lista}
    pasta = raiz / "2026 AEROFLEX" / "09 - SETEMBRO" / "10-09"
    pasta.mkdir(parents=True)
    for nome in lidos:
        (pasta / nome).write_bytes(b"%PDF-1.4 teste")
    (pasta / "anotacoes.txt").write_text("não é PDF")
    outra = raiz / "2026 AEROFLEX" / "09 - SETEMBRO" / "11-09"
    outra.mkdir()
    (outra / "BRADESCO 3179-8 11-09.pdf").write_bytes(b"%PDF-1.4 teste")   # pasta de outro dia: não entra
    abertos: list[str] = []

    def transcrever_pdf(nome, conteudo):
        abertos.append(nome)
        return lidos[nome]

    monkeypatch.setattr(transcribe_service, "transcrever_pdf", transcrever_pdf)
    monkeypatch.setenv("PASTA_EXTRATOS", str(raiz))
    return abertos


def test_pasta_de_extratos_pelo_body_json(cliente, monkeypatch, tmp_path):
    """POST /lancamentos {"data_movimento"}: lê sozinho a pasta do dia útil seguinte na PASTA_EXTRATOS."""
    abertos = _pasta_com_os_extratos_de_exemplo(tmp_path, monkeypatch)
    resposta = cliente.post("/lancamentos", headers=CABECALHO, json={"data_movimento": "2026-09-09"})
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["data_movimento"] == "2026-09-09" and len(corpo["lancamentos"]) == 44   # = plano da fixture
    assert {"pendencias", "fora_do_escopo", "extratos"} <= set(corpo)
    assert sorted(abertos) == sorted(e.arquivo for l in _resposta_lida().values() for e in l)   # só a pasta 10-09


def test_pasta_do_dia_vazia_ou_pasta_de_extratos_nao_configurada(cliente, monkeypatch, tmp_path):
    _pasta_com_os_extratos_de_exemplo(tmp_path, monkeypatch)
    vazia = cliente.post("/lancamentos", headers=CABECALHO, json={"data_movimento": "2026-09-14"})
    assert vazia.status_code == 404 and "15-09" in vazia.json()["detail"]

    monkeypatch.setenv("PASTA_EXTRATOS", "")
    sem_pasta = cliente.post("/lancamentos", headers=CABECALHO, json={"data_movimento": "2026-09-09"})
    assert sem_pasta.status_code == 503 and "PASTA_EXTRATOS" in sem_pasta.json()["detail"]

    monkeypatch.setenv("PASTA_EXTRATOS", str(tmp_path / "nao_existe"))
    assert cliente.post("/lancamentos", headers=CABECALHO, json={"data_movimento": "2026-09-09"}).status_code == 503


def test_lancamentos_nao_aceita_mais_form_data(cliente):
    resposta = cliente.post("/lancamentos", headers=CABECALHO, data={"data_movimento": "2026-09-09"})
    assert resposta.status_code == 422


class SftpFalso:
    """Árvore de pastas em memória no lugar do SFTP do cliente (caminhos remotos completos)."""

    def __init__(self, base: str, arquivos: list[str]):
        self.base = base
        self.pastas: dict[str, tuple[set, set]] = {}
        for relativo in arquivos:
            partes = relativo.split("/")
            for i in range(len(partes)):
                pasta = "/".join([base, *partes[:i]])
                subpastas, pdfs = self.pastas.setdefault(pasta, (set(), set()))
                (pdfs if i == len(partes) - 1 else subpastas).add(partes[i])
        self.lidos: list[str] = []

    def listar(self, _sftp, caminho: str):
        if caminho not in self.pastas:
            raise NaoEncontrado(caminho)
        subpastas, pdfs = self.pastas[caminho]
        return sorted(subpastas), sorted(pdfs)


def test_sftp_le_a_pasta_do_dia_seguinte_e_o_safra_atualizado(cliente, monkeypatch):
    """Movimento de 15/10 (quarta): extratos na pasta 16-10; o Safra ATUALIZADO de 15-10 salvo depois também entra.
    O ATUALIZADO substitui o original da mesma conta; o de outra data (14-10) não entra."""
    base = "/D:/A PAGAR/AEROFLEX"
    pasta = "2026 AEROFLEX/10 - OUTUBRO"
    falso = SftpFalso(base, [
        f"{pasta}/16-10/BRADESCO 3179-8 16-10.pdf",
        f"{pasta}/16-10/SAFRA 580275-7 16-10.pdf",
        f"{pasta}/16-10/SAFRA 580275-7 15-10 ATUALIZADO.pdf",
        f"{pasta}/16-10/SAFRA 580275-7 14-10 ATUALIZADO.pdf",
        f"{pasta}/15-10/ITAU 6896-9 15-10.pdf",
    ])

    @contextmanager
    def conectar(_config):
        yield "conexao"

    def ler_um(_sftp, relativo, remoto):
        falso.lidos.append(relativo)
        return "banco_0237", ExtratoConta(arquivo=relativo.rsplit("/", 1)[-1], metodo="teste", conta=None,
                                          lancamentos=[], conferencia={"saldo_anterior": None, "saldo_final": None,
                                                                       "total_creditos": 0, "total_debitos": 0,
                                                                       "diferenca": None, "ok": None})

    monkeypatch.setattr(sftp_service, "carregar_config", lambda: SimpleNamespace(pasta_base=base))
    monkeypatch.setattr(sftp_service, "conectar", conectar)
    monkeypatch.setattr(sftp_service, "listar", falso.listar)
    monkeypatch.setattr(lancamentos_router, "_ler_um", ler_um)

    resposta = cliente.post("/lancamentos/sftp", headers=CABECALHO, json={"data_movimento": "2026-10-15"})
    assert resposta.status_code == 200
    assert falso.lidos == [f"{pasta}/16-10/BRADESCO 3179-8 16-10.pdf",
                           f"{pasta}/16-10/SAFRA 580275-7 15-10 ATUALIZADO.pdf"]
    assert resposta.json()["data_movimento"] == "2026-10-15"

    # Pasta do dia ainda vazia: 404 com a pasta procurada
    vazio = cliente.post("/lancamentos/sftp", headers=CABECALHO, json={"data_movimento": "2026-10-16"})
    assert vazio.status_code == 404 and "19-10" in vazio.json()["detail"]


def test_extratos_do_robo_nao_mudam_com_as_rotas_novas(cliente, monkeypatch):
    """/extratos (usada pelo robô) continua devolvendo só a leitura do PDF."""
    from routers import extratos_router
    monkeypatch.setattr(extratos_router, "transcrever_uploads", lambda pdfs: _resposta_lida())
    resposta = cliente.post("/extratos", headers=CABECALHO, files={"arquivos": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    assert set(resposta.json()) == set(_resposta_lida())
    assert "lancamentos" in resposta.json()["banco_0237"][0] and "pendencias" not in resposta.json()


def test_feriados_do_ambiente(monkeypatch):
    monkeypatch.setenv("FERIADOS", "2026-10-12, 2026-11-02")
    assert lancamentos_service.feriados_configurados() == {date(2026, 10, 12), date(2026, 11, 2)}
