"""Banco e agência do Protheus na resposta do /transcribe, pelo número da conta que cada layout lê do PDF."""
import pytest

from services.contas_protheus import agencia, codigo_banco


@pytest.mark.parametrize("chave, codigo", [("banco_0001", "001"), ("banco_0341", "341"), ("banco_desconhecido", None)])
def test_codigo_banco(chave, codigo):
    assert codigo_banco(chave) == codigo


# Campo "conta" como cada layout devolve hoje (docs_example) -> agência do Cadastro de Bancos do Protheus
@pytest.mark.parametrize("banco, conta, esperada", [
    ("001", "41000-4", "3404"),
    ("033", "130018420", "04296"),
    ("033", "290003762", "4296"),
    ("033", "290004323", "4296"),
    ("104", "000576980561-3", "4266"),
    ("104", "4266/1292/000576980561-3", "4266"),
    ("104", "4266/1292/000572845528-6", "4266"),
    ("237", "0050542-0", "06349"),
    ("237", "0003179-8", "6349"),
    ("246", "0066093459", "0001"),
    ("246", "0066093483", "0001"),
    ("341", "0006896-9", "4685"),
    ("341", "0008311-7", "4685"),
    ("341", "4685/08311-7", "4685"),
    ("422", "000000326613-1", "03800"),
    ("422", "00580275-7", "03800"),
    ("634", "0230032-0", "0001"),
    ("707", "001500926-4", "0001"),
    ("707", "000866622-0", "0001"),
])
def test_agencia_das_contas_cadastradas(banco, conta, esperada):
    assert agencia(banco, conta) == esperada


@pytest.mark.parametrize("banco, conta", [("001", None), ("001", "99999-9"), ("260", "805605777"), (None, "41000-4")])
def test_conta_fora_do_cadastro_fica_sem_agencia(banco, conta):
    assert agencia(banco, conta) is None
