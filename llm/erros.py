class ErroIA(Exception):
    """IA indisponível, não configurada ou com resposta inválida: o PDF sem layout não pôde ser lido.

    Fica fora de llm/llm.py para os routers tratarem o erro sem carregar o LangChain na subida da API.
    """
