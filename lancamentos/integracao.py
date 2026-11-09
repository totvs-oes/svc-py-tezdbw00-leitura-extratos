"""Plano do dia em JSON para outro sistema lançar pela API do Protheus.

Cada lançamento traz os MESMOS valores que o robô preenchia na tela do Protheus (movimento_bancario.py do robô):
opção da Movimentação Bancária (FINA100), natureza, banco/agência/conta como no Cadastro de Bancos, documento,
histórico, numerário, tipo de movimento e beneficiário.

`chave` identifica o lançamento entre chamadas (mesma regra do robô: rotina + data + contas + valor + ordem): quem
lança deve guardá-la e não lançar de novo a mesma chave — chamar a rota duas vezes para o mesmo dia devolve os
mesmos lançamentos.
"""
from __future__ import annotations

from collections import Counter

from lancamentos.modelos import Conta, ItemPlano, Plano, Rendimento, Tarifa, Transferencia
from lancamentos.planejamento import documento

# Opções da rotina Movimentação Bancária (FINA100). Só 3, 4 e 7 saem do plano; as demais (5 Excluir, 6 Cancelar,
# 8 Estorno de Transferência, 9 Classificação) não são geradas.
OPCAO_PAGAR = (3, "Movimentação Bancária a Pagar (saída)")
OPCAO_RECEBER = (4, "Movimentação Bancária a Receber (entrada)")
OPCAO_TRANSFERENCIA = (7, "Transferência entre contas ou caixas")


def numerar_documentos(plano: Plano) -> None:
    """DDMMAA, DDMMAA1, DDMMAA2... por rotina + banco + dia, na ordem do plano (como o robô numerava no 1º lançamento
    do dia). Itens já numerados ficam como estão."""
    usados: Counter[tuple] = Counter()
    for item in plano.itens():
        grupo = (item.rotina, item.banco_documento(), item.data)
        if item.documento is None:
            item.documento = documento(item.data, usados[grupo])
        usados[grupo] += 1


def _conta(conta: Conta) -> dict:
    return {"banco": conta.banco, "agencia": conta.agencia, "conta": conta.numero}


def _lancamento(item: ItemPlano, constantes: dict) -> dict:
    base = {"chave": item.chave, "data": item.data.isoformat(), "valor": str(item.valor),
            "historico": item.historico, "documento": item.documento, "filial": constantes["filial"]}
    if isinstance(item, Transferencia):
        opcao = OPCAO_TRANSFERENCIA
        campos = {"natureza": constantes["natureza_transferencia"], "origem": _conta(item.origem),
                  "destino": _conta(item.destino), "tipo_mov": constantes["tipo_mov_transferencia"],
                  "beneficiario": constantes["beneficiario_transferencia"]}
    elif isinstance(item, Rendimento):   # antes de Tarifa: Rendimento é subclasse de Tarifa
        opcao = OPCAO_RECEBER
        campos = {"natureza": constantes["natureza_rendimento"], **_conta(item.conta),
                  "numerario": constantes["numerario"], "beneficiario": constantes["beneficiario_rendimento"]}
    elif isinstance(item, Tarifa):
        opcao = OPCAO_PAGAR
        campos = {"natureza": item.natureza or constantes["natureza_tarifa"], **_conta(item.conta),
                  "numerario": constantes["numerario"]}
    else:
        raise TypeError(f"Item de plano sem opção na Movimentação Bancária: {type(item).__name__}")
    return {"rotina": item.rotina.value, "opcao": opcao[0], "descricao_opcao": opcao[1], **base, **campos,
            "origem_extrato": item.origem_extrato, "aviso": item.aviso}


def plano_para_integracao(plano: Plano, constantes: dict) -> dict:
    numerar_documentos(plano)
    return {
        "data_movimento": plano.data_movimento.isoformat(),
        "lancamentos": [_lancamento(i, constantes) for i in plano.itens()],
        "pendencias": [{"arquivo": p.arquivo, "data": p.data.isoformat() if p.data else None,
                        "historico": p.historico, "valor": str(p.valor) if p.valor is not None else None,
                        **(_conta(p.conta) if p.conta else {}), "motivo": p.motivo, "acao": p.acao}
                       for p in plano.pendencias],
        "baixa_manual": [{"arquivo": b.arquivo, "data": b.data.isoformat(), "historico": b.historico,
                          "valor": str(b.valor), **_conta(b.conta), "motivo": b.motivo, "acao": b.acao}
                         for b in plano.baixa_manual],
        "fora_do_escopo": [{"arquivo": l.arquivo, "data": l.data.isoformat(), "historico": l.historico,
                            "operacao": l.operacao, "valor": str(l.valor), **_conta(l.conta)}
                           for l in plano.fora_do_escopo],
        "extratos": [{"arquivo": e.arquivo, **(_conta(e.conta) if e.conta else {"banco": e.banco}),
                      "detalhe_de_tarifas": e.eh_detalhe_tarifas, "metodo": e.metodo, "aviso": e.aviso,
                      "conferencia_ok": e.conferencia_ok}
                     for e in plano.extratos],
    }
