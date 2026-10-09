import pytest

from services.normalizacao import (
    eh_linha_de_saldo,
    identificar_banco,
    normalizar_data,
    parse_saldo,
    parse_valor,
)


@pytest.mark.parametrize("texto, esperado", [
    ("1.234,56", (1234.56, None)),
    ("-12,11", (12.11, "debito")),
    ("12,11-", (12.11, "debito")),
    ("2,00 D", (2.0, "debito")),
    ("68.875,15 C", (68875.15, "credito")),
    ("+5,00", (5.0, "credito")),
    ("R$ 100.691,20", (100691.2, None)),
    ("-R$ 43,79", (43.79, "debito")),      # Daycoval: sinal antes do R$
    ("", (None, None)),
    (None, (None, None)),
    ("sem valor", (None, None)),
])
def test_parse_valor(texto, esperado):
    assert parse_valor(texto) == esperado


def test_parse_saldo_negativo():
    assert parse_saldo("-R$ 1.000,00") == -1000.0
    assert parse_saldo("1.000,00 D") == -1000.0
    assert parse_saldo("1.000,00") == 1000.0


@pytest.mark.parametrize("data, ano, esperado", [
    ("09/09/2026", None, "09/09/2026"),
    ("09/09", "2026", "09/09/2026"),
    ("09/09", None, "09/09"),
    (None, "2026", None),
])
def test_normalizar_data(data, ano, esperado):
    assert normalizar_data(data, ano) == esperado


@pytest.mark.parametrize("nome, codigo", [
    ("BRADESCO 3179-8 10-09.pdf", "0237"),
    ("SANTANDER 130018420 10-09.pdf", "0033"),
    ("DAYCOVAL 1500926-4 04-09.pdf", "0707"),
    ("BANCO DO BRASIL 410004 10-09.pdf", "0001"),
    ("ITAU 6896-9 10-09.pdf", "0341"),
])
def test_identificar_banco_pelo_nome_do_arquivo(nome, codigo):
    assert identificar_banco("", nome) == codigo


def test_saldo_vinculado_liberado_e_lancamento_e_nao_linha_de_saldo():
    assert eh_linha_de_saldo("SALDO ANTERIOR")
    assert eh_linha_de_saldo("S A L D O DO DIA")
    assert not eh_linha_de_saldo("SALDO VINCULADO LIBERADO 000000")
