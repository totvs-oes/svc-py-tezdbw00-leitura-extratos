import os

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

from schemas.extrato import ExtracaoPagina

base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
model = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")

llm = ChatOllama(
    base_url=base_url,
    model=model,
    temperature=0,
    reasoning=False,
    num_ctx=16384,
)

system = """Você é um extrator de dados de extratos bancários brasileiros.
Você recebe o texto de UMA página de extrato com o layout preservado: cada linha da tabela é uma linha de texto e as colunas são separadas por espaços.

Regras:
1. Extraia TODOS os lançamentos (movimentações) da tabela de lançamentos, na ordem em que aparecem. Não pule e não invente linhas.
2. NÃO inclua linhas de saldo (SALDO ANTERIOR, SALDO DIA, SALDO TOTAL, SALDO INICIAL, "S A L D O", saldo disponível, saldo aplicado etc.), linhas de total, limites, lançamentos futuros, cabeçalhos ou rodapés.
   Atenção: históricos como "SALDO VINCULADO LIBERADO" são movimentações reais e DEVEM ser incluídos.
3. data: copie como aparece (dd/mm/aaaa ou dd/mm). Se a linha do lançamento não tiver data, use null.
4. historico: descrição do lançamento. Se estiver quebrada em várias linhas (acima ou abaixo da linha do valor), junte tudo em um único texto. Não inclua número de documento nem saldo.
5. valor: copie EXATAMENTE o texto do valor do lançamento, com sinal e sufixo C/D se houver (ex.: "-12,11", "2,00 D", "68.875,15 C", "51.315,72"). Nunca use o valor da coluna de saldo.
6. operacao: "credito" se o dinheiro entra na conta, "debito" se sai. Use o sinal, o sufixo C/D, a coluna (Crédito/Débito) ou a coluna Operação.
7. conta: número da conta corrente que aparece no cabeçalho (ex.: "Conta: 130018420" -> "130018420", "CC: 0003179-8" -> "0003179-8"). null somente se não houver.
8. saldo_anterior / saldo_final: texto do saldo no início e no fim do período, se aparecerem nesta página, senão null.
   Use sempre o valor da coluna de SALDO, com sufixo C/D se houver. Se a linha de saldo tiver mais de um valor, o saldo é o último (mais à direita).
   saldo_final é o último saldo que aparece na coluna Saldo da tabela de lançamentos. Ignore quadros de resumo fora da tabela (saldo disponível, saldo total, investimentos, limites)."""

template = ChatPromptTemplate.from_messages([
    ("system", system),
    ("human", "### Página do extrato:\n{pagina}"),
])

extracao_chain = template | llm.with_structured_output(ExtracaoPagina, method="json_schema")


def extrair_pagina(pagina: str) -> ExtracaoPagina:
    return extracao_chain.invoke({"pagina": pagina})
