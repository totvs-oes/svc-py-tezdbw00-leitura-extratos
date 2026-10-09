"""Relatório "Movimentação de Títulos" do Itaú (TARIFAS ITAU): uma tarifa por boleto, conferida pelo resumo."""
from collections import Counter
from decimal import Decimal

import pytest

from services.transcribe_service import PASTA_EXEMPLOS, transcrever_arquivo

ARQUIVO = PASTA_EXEMPLOS / "TARIFAS ITAU 09-09.pdf"
pytestmark = pytest.mark.skipif(not ARQUIVO.exists(), reason="PDF de exemplo ausente (docs_example/ fica fora do git)")


@pytest.fixture(scope="module")
def extrato():
    return transcrever_arquivo(ARQUIVO)


def test_le_com_o_layout_proprio(extrato):
    chave, e = extrato
    assert (chave, e.metodo, e.conta) == ("banco_0341", "layout Tarifas Itaú", "4685/08311-7")


def test_uma_tarifa_por_boleto_que_soma_o_total_de_deducoes(extrato):
    _, e = extrato
    tipos = Counter(l.historico.split(" ")[1] for l in e.lancamentos)
    assert tipos == {"COBRANCA": 363, "MANUT": 11}      # código 01 (0,89) e histórico TM (1,79)
    assert sum(Decimal(str(l.valor)) for l in e.lancamentos) == Decimal("342.76")
    assert e.conferencia.ok is True and e.conferencia.diferenca == 0
    assert all(l.operacao == "debito" and l.data == "09/09/2026" for l in e.lancamentos)


def test_primeira_linha_de_cada_pagina_nao_se_perde(extrato):
    """A 1ª linha de cada página sai grudada no cabeçalho na extração; a tarifa dela tem que ser lida."""
    _, e = extrato
    historicos = [l.historico for l in e.lancamentos]
    assert historicos[0] == "TAR COBRANCA 00118299-7 JR DISTRIBUIDORA DE ESTOPAS E"
    assert any(h.startswith("TAR COBRANCA 50002758-6") for h in historicos)   # 1ª linha da página 2


def test_extrato_normal_do_itau_continua_no_layout_itau():
    _, e = transcrever_arquivo(PASTA_EXEMPLOS / "ITAU 6896-9 10-09.pdf")
    assert e.metodo == "layout Itaú"


@pytest.mark.parametrize("arquivo, quantidade, total", [
    ("TARIFAS ITAU 10-09.pdf", 110, "113.20"),   # resumo com "Custas 0,00" na linha: total pela posição
    ("TARIFAS ITAU 11-09.pdf", 47, "44.53"),     # + TN/TQ de negativação (53,00) fora: total 97,53
])
def test_outros_dias_fecham_com_o_total_de_deducoes(arquivo, quantidade, total):
    caminho = PASTA_EXEMPLOS / arquivo
    if not caminho.exists():
        pytest.skip(f"{arquivo} ausente")
    _, e = transcrever_arquivo(caminho)
    assert len(e.lancamentos) == quantidade
    assert sum(Decimal(str(l.valor)) for l in e.lancamentos) == Decimal(total)
    assert e.conferencia.ok is True


def test_boleto_de_outra_carteira_tem_o_proprio_nosso_numero():
    """10/09/2026: o TM da carteira 157 (000407527 BAZAR TUDO) saía com o nosso nº do boleto anterior."""
    caminho = PASTA_EXEMPLOS / "TARIFAS ITAU 10-09.pdf"
    if not caminho.exists():
        pytest.skip("PDF ausente")
    _, e = transcrever_arquivo(caminho)
    assert e.lancamentos[-1].historico.startswith("TAR MANUT TIT VENCIDO 000407527 BAZAR TUDO")
