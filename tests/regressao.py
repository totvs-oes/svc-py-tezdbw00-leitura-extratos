"""Regressão dos layouts: resumo da leitura de cada PDF de docs_example/ que tem layout próprio.

O resumo não guarda o texto dos extratos (dados do cliente): só totais, saldos e uma impressão digital
(SHA-256) dos lançamentos. Qualquer mudança em data, histórico, operação ou valor muda a impressão digital.

Mudou um layout DE PROPÓSITO? Confira a leitura e regrave o esperado:
    venv\\Scripts\\python -m tests.regressao
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from services.layouts import identificar_layout
from services.normalizacao import zona_de_identificacao
from services.pdf_service import extrair_linhas, renderizar
from services.transcribe_service import PASTA_EXEMPLOS, transcrever_arquivo

ESPERADO = Path(__file__).parent / "fixtures" / "esperado_layouts.json"


def tem_layout(arquivo: Path) -> bool:
    """True se o PDF é lido por layout (os que iriam para a IA ficam fora: teste não chama a IA)."""
    paginas_linhas = extrair_linhas(str(arquivo))
    paginas = ["\n".join(renderizar(linha) for linha in pagina) for pagina in paginas_linhas]
    return identificar_layout(arquivo.name, zona_de_identificacao(paginas), paginas_linhas) is not None


def resumo(arquivo: Path) -> dict:
    chave, extrato = transcrever_arquivo(arquivo)
    lancamentos = [l.model_dump() for l in extrato.lancamentos]
    conferencia = extrato.conferencia
    return {
        "banco": chave,
        "metodo": extrato.metodo,
        "conta": extrato.conta,
        "lancamentos": len(lancamentos),
        "total_creditos": conferencia.total_creditos,
        "total_debitos": conferencia.total_debitos,
        "saldo_anterior": conferencia.saldo_anterior,
        "saldo_final": conferencia.saldo_final,
        "conferencia_ok": conferencia.ok,
        "impressao_digital": hashlib.sha256(
            json.dumps(lancamentos, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
    }


def pdfs_com_layout(pasta: Path = PASTA_EXEMPLOS) -> list[Path]:
    return [a for a in sorted(pasta.glob("*.pdf")) if tem_layout(a)]


def carregar_esperado() -> dict | None:
    return json.loads(ESPERADO.read_text(encoding="utf-8")) if ESPERADO.exists() else None


if __name__ == "__main__":
    esperado = {a.name: resumo(a) for a in pdfs_com_layout()}
    ESPERADO.parent.mkdir(parents=True, exist_ok=True)
    ESPERADO.write_text(json.dumps(esperado, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for nome, r in esperado.items():
        print(f"{r['metodo']:<22} ok={r['conferencia_ok']!s:<5} {r['lancamentos']:>4} lanç.  {nome}")
    print(f"{len(esperado)} arquivo(s) -> {ESPERADO}", file=sys.stderr)
