"""Formatos vistos nos extratos de 10 a 16/09/2026 (pastas 11-09 a 16-09). PDFs reais em docs_example/ (fora do git)."""
from decimal import Decimal

import pytest

from services.transcribe_service import PASTA_EXEMPLOS, transcrever_arquivo


def _ler(arquivo):
    caminho = PASTA_EXEMPLOS / arquivo
    if not caminho.exists():
        pytest.skip(f"{arquivo} ausente")
    return transcrever_arquivo(caminho)[1]


def test_abc_extrato_detalhado_le_dois_dias_sem_numero_do_documento_no_historico():
    e = _ler("ABC 6609345-9 11-09.pdf")
    assert e.metodo == "layout ABC" and e.conferencia.ok is True
    assert {l.data for l in e.lancamentos} == {"10/09/2026", "11/09/2026"}
    assert any(l.historico == "APLICACAO FINANCEIRA" and l.operacao == "debito" for l in e.lancamentos)


def test_caixa_le_o_periodo_inteiro_e_nao_so_o_dia_da_emissao():
    e = _ler("BANCO CAIXA 11-09.pdf")
    assert e.conferencia.ok is True
    assert {"09/09/2026", "10/09/2026", "11/09/2026"} <= {l.data for l in e.lancamentos}


def test_caixa_vinculada_com_saldo_anterior_fora_da_tabela():
    e = _ler("CAIXA VINCULADA 11-09.pdf")
    assert e.metodo == "layout Caixa vinculada" and e.conferencia.ok is True
    transferencia = [l for l in e.lancamentos if l.data == "10/09/2026" and l.operacao == "debito"]
    assert [(l.historico.split(" 0787")[0], l.valor) for l in transferencia] == [("TRANSF RECURSO AGENCIA", 490401.14)]


def test_tarifas_bb_uma_por_titulo():
    i, ii = _ler("TARIFAS BB 09-09 I.pdf"), _ler("TARIFAS BB 09-09 II.pdf")
    # 7,47 + 6,87 = 14,34 = "Tar. agrupadas" do extrato BB de 09/09
    assert sum(Decimal(str(l.valor)) for l in i.lancamentos + ii.lancamentos) == Decimal("14.34")
    assert i.conta == "41000-4" and all(l.operacao == "debito" for l in i.lancamentos)
    iii = _ler("TARIFAS BB 11-09 III.pdf")   # instruções diversas: linha DCA (cartório, tarifa 0,00) fica de fora
    assert [l.valor for l in iii.lancamentos] == [6.87, 6.87]


def test_tribanco_com_leitor_fixo_e_so_o_saldo_disponivel():
    """Tribanco (cadastrado no Protheus em 09/10/2026: banco 634). SALDO VINCULADO/BLOQUEADO zerados são ignorados."""
    e = _ler("TRIBANCO 11-09.pdf")
    assert (e.metodo, e.conta, e.conferencia.ok) == ("layout Tribanco", "0230032-0", True)
    assert [(l.operacao, l.valor, l.historico) for l in e.lancamentos] == [
        ("debito", 122.1, "TAR MANUTENCAO C/C-REF.09/2026"), ("credito", 97040.68, "TED C RECEBIDA-MARTINS COMERCIO E S")]
