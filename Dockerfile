# Serviço de leitura de extratos (FastAPI + PyMuPDF)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependências antes do código: a camada fica em cache enquanto o requirements.txt não mudar
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Não roda como root
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/docs', timeout=4)"

# Sem --reload em produção
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
