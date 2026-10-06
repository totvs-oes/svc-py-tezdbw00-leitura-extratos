"""Regressão dos layouts com os PDFs reais de docs_example/ (fora do git: sem a pasta, os testes são pulados)."""
import pytest

from services.transcribe_service import PASTA_EXEMPLOS
from tests.regressao import carregar_esperado, resumo

ESPERADO = carregar_esperado() or {}
sem_pdfs = pytest.mark.skipif(not PASTA_EXEMPLOS.exists(), reason="docs_example/ ausente (PDFs do cliente ficam fora do git)")


@sem_pdfs
@pytest.mark.parametrize("nome", sorted(ESPERADO))
def test_leitura_igual_a_referencia(nome):
    arquivo = PASTA_EXEMPLOS / nome
    if not arquivo.exists():
        pytest.skip(f"{nome} não está em docs_example/")
    atual = resumo(arquivo)
    assert atual == ESPERADO[nome], (
        f"A leitura de {nome} mudou. Se foi de propósito, confira e regrave: venv\\Scripts\\python -m tests.regressao")


@sem_pdfs
@pytest.mark.parametrize("nome", sorted(ESPERADO))
def test_conferencia_de_saldo_nunca_falha(nome):
    """Extrato com saldo no PDF tem que fechar ao centavo (None = o banco não informa saldo: Safra, tarifas)."""
    assert ESPERADO[nome]["conferencia_ok"] in (True, None)


def test_referencia_cobre_todos_os_bancos():
    bancos = {r["metodo"] for r in ESPERADO.values()}
    assert bancos >= {"layout ABC", "layout Caixa", "layout Banco do Brasil", "layout Bradesco", "layout Itaú",
                      "layout Safra", "layout Santander", "layout Daycoval", "layout Tarifas ABC", "layout Tarifas Itaú"}
