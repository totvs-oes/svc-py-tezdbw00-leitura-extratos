"""Sobe a API sem janela (pythonw.exe) com log em arquivo: usado pela tarefa agendada no servidor da cliente.

    venv\\Scripts\\pythonw.exe executar_api.py [porta]          (padrão 5000, só em 127.0.0.1)

Sem console, o pythonw não tem saída padrão e o uvicorn cai ao configurar o log; aqui o log vai para
logs\\api.log (5 MB x 3 arquivos). Sem reload: com reload sobra um processo filho segurando a porta.
Se mesmo assim abrir um console só para a API (Python portátil), a janela é escondida.
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


def esconder_console_proprio() -> None:
    """Esconde a janela de console criada só para este processo.

    No Python portátil (pacote NuGet) o pythonw do venv acaba abrindo console: fechar essa janela derrubaria a API.
    Se outro processo usa o mesmo console (ex.: rodado à mão num PowerShell), não mexe."""
    if sys.platform != "win32":
        return
    import ctypes
    import os
    kernel32 = ctypes.windll.kernel32
    janela = kernel32.GetConsoleWindow()
    if not janela:
        return
    lista = (ctypes.c_uint32 * 8)()
    quantidade = kernel32.GetConsoleProcessList(lista, 8)
    outros = set(lista[:quantidade]) - {os.getpid()}
    # o lançador do venv (venv\Scripts\python*.exe, nosso pai) também fica preso ao console; qualquer outro é um terminal
    if outros <= {os.getppid()} and all(_nome_do_executavel(pid).lower().startswith("python") for pid in outros):
        ctypes.windll.user32.ShowWindow(janela, 0)   # SW_HIDE


def _nome_do_executavel(pid: int) -> str:
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    processo = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not processo:
        return ""
    try:
        caminho = ctypes.create_unicode_buffer(32768)
        tamanho = wintypes.DWORD(len(caminho))
        if not kernel32.QueryFullProcessImageNameW(processo, 0, caminho, ctypes.byref(tamanho)):
            return ""
        return Path(caminho.value).name
    finally:
        kernel32.CloseHandle(processo)


def main() -> None:
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    esconder_console_proprio()
    PASTA_LOGS.mkdir(exist_ok=True)
    if sys.stdout is None or sys.stderr is None:   # pythonw: print/traceback sem destino derrubariam o processo
        saida = open(PASTA_LOGS / "api_console.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or saida
        sys.stderr = sys.stderr or saida
    uvicorn.run("main:app", host="127.0.0.1", port=porta, log_config=configuracao_de_log(PASTA_LOGS / "api.log"))


if __name__ == "__main__":
    main()
