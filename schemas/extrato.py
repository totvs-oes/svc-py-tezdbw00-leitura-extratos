from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schemas usados como "contrato" de saída da LLM (structured output).
# Os valores vêm como TEXTO, exatamente como estão no PDF; a conversão para
# número/data é feita em Python (services/normalizacao.py), que é determinístico.
# ---------------------------------------------------------------------------

class LancamentoLLM(BaseModel):
    data: str | None = Field(description="Data do lançamento como aparece (dd/mm/aaaa ou dd/mm). null se a linha não tiver data.")
    historico: str = Field(description="Descrição do lançamento, juntando as linhas quebradas.")
    valor: str = Field(description='Texto exato do valor do lançamento, com sinal e sufixo C/D. Ex.: "-12,11", "2,00 D", "68.875,15 C".')
    operacao: Literal["credito", "debito"]


class ExtracaoPagina(BaseModel):
    conta: str | None = Field(default=None, description="Número da conta corrente, se aparecer na página.")
    saldo_anterior: str | None = Field(default=None, description="Texto do saldo anterior/inicial do período, se aparecer na página.")
    saldo_final: str | None = Field(default=None, description="Texto do saldo final do período, se aparecer na página.")
    lancamentos: list[LancamentoLLM]


# ---------------------------------------------------------------------------
# Schemas da resposta da API
# ---------------------------------------------------------------------------

class Lancamento(BaseModel):
    data: str | None
    historico: str
    operacao: Literal["credito", "debito"]
    valor: float


class MovimentacaoNaoListada(BaseModel):
    """Movimentação que o banco não lista como lançamento, deduzida dos saldos diários do próprio extrato."""
    data: str | None
    valor: float = Field(description="Positivo = entrou na conta, negativo = saiu.")
    descricao: str
    explicada: bool = Field(description="True se o extrato mostra atividade de aplicação automática que justifica a diferença.")


class SaldoInformado(BaseModel):
    """Linha de saldo que o banco imprime no meio dos lançamentos (ex.: Safra "SALDO CONTA CORRENTE")."""
    data: str | None
    descricao: str
    valor: float = Field(description="Com sinal: negativo = saldo devedor.")


class Conferencia(BaseModel):
    saldo_anterior: float | None
    saldo_final: float | None
    total_creditos: float
    total_debitos: float
    movimentacoes_nao_listadas: list[MovimentacaoNaoListada] = []
    diferenca: float | None = Field(description="saldo_anterior + créditos - débitos + não listadas - saldo_final. 0 = extração bate com o extrato.")
    ok: bool | None


class ExtratoConta(BaseModel):
    arquivo: str
    metodo: str = Field(description='Como foi extraído: "layout <banco>" (parser fixo), "ia" (fallback) ou "nenhum".')
    aviso: str | None = Field(default=None, description="Problema que impediu ou comprometeu a leitura do arquivo.")
    conta: str | None
    lancamentos: list[Lancamento]
    conferencia: Conferencia
    saldos_informados: list[SaldoInformado] = Field(
        default=[], description="Saldos que o banco imprime como linhas (só layouts sem coluna de saldo, ex.: Safra).")


# ---------------------------------------------------------------------------
# Resposta do POST /transcribe: o mesmo extrato, com a opção da rotina Movimentação Bancária (FINA100) do Protheus em
# cada lançamento, para quem for lançar pela API do Protheus. As rotas que o robô usa (/extratos) não mudam.
# ---------------------------------------------------------------------------

# 3 = Movimentação Bancária a Pagar (saída), 4 = a Receber (entrada). As demais opções da FINA100 (5 Excluir, 6 Cancelar,
# 7 Transferência entre contas ou caixas, 8 Estorno de Transferência, 9 Classificação) não saem só do extrato.
OPCOES_MOVIMENTACAO_BANCARIA: dict[str, tuple[int, str]] = {
    "debito": (3, "Movimentação Bancária a Pagar (saída)"),
    "credito": (4, "Movimentação Bancária a Receber (entrada)"),
}


class LancamentoComOpcao(Lancamento):
    opcao: int = Field(description="Opção da Movimentação Bancária (FINA100) no Protheus: 3 = a Pagar, 4 = a Receber.")
    descricao_opcao: str


class ExtratoContaComOpcao(ExtratoConta):
    lancamentos: list[LancamentoComOpcao]

    @classmethod
    def de(cls, extrato: ExtratoConta) -> "ExtratoContaComOpcao":
        lancamentos = [LancamentoComOpcao(**l.model_dump(), opcao=OPCOES_MOVIMENTACAO_BANCARIA[l.operacao][0],
                                          descricao_opcao=OPCOES_MOVIMENTACAO_BANCARIA[l.operacao][1])
                       for l in extrato.lancamentos]
        return cls(**(extrato.model_dump() | {"lancamentos": lancamentos}))
