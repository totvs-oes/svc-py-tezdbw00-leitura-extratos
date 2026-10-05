import os
from functools import lru_cache

import openai
from langchain_core.exceptions import OutputParserException
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from llm.erros import ErroIA
from schemas.extrato import ExtracaoPagina

base_url = os.getenv("LLM_BASE_API_URL")
model = os.getenv("LLM_MODEL")


system = """Você é um extrator de dados de extratos bancários brasileiros.
Você recebe o texto de UMA página de extrato com o layout preservado: cada linha da tabela é uma linha de texto e as colunas são separadas por espaços.

Regras:
1. Extraia TODOS os lançamentos (movimentações) da tabela de lançamentos, na ordem em que aparecem. Não pule e não invente linhas.
2. NÃO inclua linhas de saldo (SALDO ANTERIOR, SALDO DIA, SALDO TOTAL, SALDO INICIAL, "S A L D O", saldo disponível, saldo aplicado etc.), linhas de total (inclusive "Total de entradas" e "Total de saídas"), limites, lançamentos futuros, cabeçalhos ou rodapés.
   Atenção: históricos como "SALDO VINCULADO LIBERADO" são movimentações reais e DEVEM ser incluídos.
3. data: copie como aparece (dd/mm/aaaa ou dd/mm). Se a linha do lançamento não tiver data, use null.
4. historico: descrição do lançamento. Se estiver quebrada em várias linhas (acima ou abaixo da linha do valor), junte tudo em um único texto. Não inclua número de documento nem saldo.
5. valor: copie EXATAMENTE o texto do valor do lançamento, com sinal e sufixo C/D se houver (ex.: "-12,11", "2,00 D", "68.875,15 C", "51.315,72"). Nunca use o valor da coluna de saldo.
6. operacao: "credito" se o dinheiro entra na conta, "debito" se sai. Use o sinal, o sufixo C/D, a coluna (Crédito/Débito) ou a coluna Operação.
   Se os valores não têm sinal e o extrato agrupa por seção ("Total de entradas" / "Total de saídas", "Entradas" / "Saídas"), a seção define a operação de cada lançamento abaixo dela.
   Uma página pode começar no meio de uma seção: use o final da página anterior (enviado como contexto) para saber qual é.
7. conta: número da conta do titular do extrato, que aparece no cabeçalho (ex.: "Conta: 130018420" -> "130018420", "CC: 0003179-8" -> "0003179-8").
   Nunca use a conta de uma contraparte (ex.: conta de destino/origem de um Pix). null somente se não houver.
8. saldo_anterior / saldo_final: texto do saldo no início e no fim do período, se aparecerem nesta página, senão null.
   Se a tabela tiver coluna de SALDO, use o valor dessa coluna, com sufixo C/D se houver. Se a linha de saldo tiver mais de um valor, o saldo é o último (mais à direita).
   saldo_final é o último saldo da coluna Saldo; nesse caso ignore quadros de resumo fora da tabela (saldo disponível, saldo total, investimentos, limites).
   Se a tabela NÃO tiver coluna de saldo, use o saldo inicial e o saldo final do período informados no resumo do extrato.
   O resumo vale para o período inteiro: se ele estiver nesta página (mesmo sendo a primeira), preencha os DOIS,
   saldo_anterior com o saldo inicial e saldo_final com o "Saldo final do período"."""

template = ChatPromptTemplate.from_messages([
    ("system", system),
    ("human", "### Final da página anterior (só contexto: NÃO extraia lançamentos daqui):\n{contexto}\n\n"
              "### Página do extrato:\n{pagina}"),
])

# Linhas do fim da página anterior enviadas como contexto (seção em andamento, data do dia)
LINHAS_DE_CONTEXTO = 25


@lru_cache(maxsize=1)
def _extracao_chain():
    """Cria o cliente só no primeiro uso: a API sobe mesmo sem a chave, já que a IA só é usada sem layout."""
    api_key = os.getenv("TOKEN_API_LLM")
    if not api_key:
        raise ErroIA("TOKEN_API_LLM não configurado no .env.")
    llm = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=0,
        timeout=120,
        max_retries=2,
    )
    return template | llm.with_structured_output(ExtracaoPagina, method="json_schema")


def extrair_pagina(pagina: str, pagina_anterior: str = "") -> ExtracaoPagina:
    chain = _extracao_chain()
    contexto = "\n".join(pagina_anterior.splitlines()[-LINHAS_DE_CONTEXTO:]) or "(primeira página)"
    try:
        return chain.invoke({"pagina": pagina, "contexto": contexto})
    except openai.AuthenticationError as erro:
        raise ErroIA("Chave do proxy de IA recusada (TOKEN_API_LLM).") from erro
    except openai.RateLimitError as erro:
        raise ErroIA("Limite de uso do proxy de IA atingido.") from erro
    except (openai.APIConnectionError, openai.APITimeoutError) as erro:
        raise ErroIA(f"Sem conexão com o proxy de IA ({base_url}).") from erro
    except openai.APIStatusError as erro:
        raise ErroIA(f"Proxy de IA respondeu HTTP {erro.status_code}: {str(erro)[:200]}") from erro
    except (OutputParserException, ValidationError) as erro:
        raise ErroIA(f"Resposta da IA fora do formato esperado: {str(erro)[:200]}") from erro
