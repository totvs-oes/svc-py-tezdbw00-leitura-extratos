"""Sobe a API sem janela (pythonw.exe) com log em arquivo: usado pela tarefa agendada no servidor da cliente.

    venv\\Scripts\\pythonw.exe executar_api.py [porta]          (padrão 5000, só em 127.0.0.1)

Sem console, o pythonw não tem saída padrão e o uvicorn cai ao configurar o log; aqui o log vai para
logs\\api.log (5 MB x 3 arquivos). Sem reload: com reload sobra um processo filho segurando a porta.
"""
import sys
from pathlib import Path

import uvicorn

PASTA_LOGS = Path(__file__).resolve().parent / "logs"


def configuracao_de_log(arquivo: Path) -> dict:
    manipulador = {"class": "logging.handlers.RotatingFileHandler", "filename": str(arquivo), "encoding": "utf-8",
                   "maxBytes": 5_000_000, "backupCount": 3, "formatter": "padrao"}
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"padrao": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
        "handlers": {"arquivo": manipulador},
        "loggers": {nome: {"handlers": ["arquivo"], "level": "INFO", "propagate": False}
                    for nome in ("uvicorn", "uvicorn.error", "uvicorn.access")},
        "root": {"handlers": ["arquivo"], "level": "INFO"},
    }


def main() -> None:
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    PASTA_LOGS.mkdir(exist_ok=True)
    if sys.stdout is None or sys.stderr is None:   # pythonw: print/traceback sem destino derrubariam o processo
        saida = open(PASTA_LOGS / "api_console.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or saida
        sys.stderr = sys.stderr or saida
    uvicorn.run("main:app", host="127.0.0.1", port=porta, log_config=configuracao_de_log(PASTA_LOGS / "api.log"))


if __name__ == "__main__":
    main()
