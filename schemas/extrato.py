from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Schemas usados como "contrato" de saída da LLM (structured output).
# Os valores vêm como TEXTO, exatamente como estão no PDF; a conversão para
# número/data é feita em Python (services/normalizacao.py), que é determinístico.
# ---------------------------------------------------------------------------

class LancamentoLLM(BaseModel):
    data: Optional[str] = Field(description="Data do lançamento como aparece (dd/mm/aaaa ou dd/mm). null se a linha não tiver data.")
    historico: str = Field(description="Descrição do lançamento, juntando as linhas quebradas.")
    valor: str = Field(description='Texto exato do valor do lançamento, com sinal e sufixo C/D. Ex.: "-12,11", "2,00 D", "68.875,15 C".')
    operacao: Literal["credito", "debito"]


class ExtracaoPagina(BaseModel):
    conta: Optional[str] = Field(default=None, description="Número da conta corrente, se aparecer na página.")
    saldo_anterior: Optional[str] = Field(default=None, description="Texto do saldo anterior/inicial do período, se aparecer na página.")
    saldo_final: Optional[str] = Field(default=None, description="Texto do saldo final do período, se aparecer na página.")
    lancamentos: list[LancamentoLLM]


# ---------------------------------------------------------------------------
# Schemas da resposta da API
# ---------------------------------------------------------------------------

class Lancamento(BaseModel):
    data: Optional[str]
    historico: str
    operacao: Literal["credito", "debito"]
    valor: float


class MovimentacaoNaoListada(BaseModel):
    """Movimentação que o banco não lista como lançamento, deduzida dos saldos diários do próprio extrato."""
    data: Optional[str]
    valor: float = Field(description="Positivo = entrou na conta, negativo = saiu.")
    descricao: str
    explicada: bool = Field(description="True se o extrato mostra atividade de aplicação automática que justifica a diferença.")


class Conferencia(BaseModel):
    saldo_anterior: Optional[float]
    saldo_final: Optional[float]
    total_creditos: float
    total_debitos: float
    movimentacoes_nao_listadas: list[MovimentacaoNaoListada] = []
    diferenca: Optional[float] = Field(description="saldo_anterior + créditos - débitos + não listadas - saldo_final. 0 = extração bate com o extrato.")
    ok: Optional[bool]


class ExtratoConta(BaseModel):
    arquivo: str
    metodo: str = Field(description='Como foi extraído: "layout <banco>" (parser fixo), "ia" (fallback) ou "nenhum".')
    aviso: Optional[str] = Field(default=None, description="Problema que impediu ou comprometeu a leitura do arquivo.")
    conta: Optional[str]
    lancamentos: list[Lancamento]
    conferencia: Conferencia
