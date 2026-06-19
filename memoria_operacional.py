"""
Memória operacional — observação/descrição normalizada -> status aprendido.

Estrutura estrita: dict plano em data/memoria_operacional.json.
Consultada após aprendizado_regras.json e antes do regex.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

from aprendizado_regras import STATUS_PARA_TIPO_FRETE

PROJECT_ROOT = Path(__file__).resolve().parent
ARQUIVO_MEMORIA = PROJECT_ROOT / "data" / "memoria_operacional.json"

_cache_memoria: dict[str, str] | None = None


def _sem_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_texto_memoria(observacao: str, descricao: str = "") -> str:
    """Chave plana: minúscula, sem acentos, só alfanumérico."""
    bruto = f"{observacao or ''} {descricao or ''}".strip()
    texto = _sem_acentos(bruto).lower()
    return re.sub(r"[^a-z0-9]+", "", texto)


def carregar_memoria(recarregar: bool = False) -> dict[str, str]:
    global _cache_memoria
    if _cache_memoria is not None and not recarregar:
        return _cache_memoria

    memoria: dict[str, str] = {}
    try:
        if ARQUIVO_MEMORIA.exists():
            bruto = json.loads(ARQUIVO_MEMORIA.read_text(encoding="utf-8"))
            if isinstance(bruto, dict):
                for chave, valor in bruto.items():
                    if str(chave).startswith("_"):
                        continue
                    if isinstance(valor, str):
                        memoria[str(chave)] = valor
    except Exception:
        memoria = {}

    _cache_memoria = memoria
    return memoria


def salvar_memoria(entradas: dict[str, str]) -> int:
    global _cache_memoria
    ARQUIVO_MEMORIA.parent.mkdir(parents=True, exist_ok=True)

    existentes = carregar_memoria()
    merged = {**existentes}
    novas = 0
    for chave, valor in entradas.items():
        if chave.startswith("_") or not isinstance(valor, str) or not chave.strip():
            continue
        merged[str(chave)] = valor.strip()
        novas += 1

    payload = {
        "_versao": "1",
        "_descricao": "Texto normalizado da observacao/descricao -> status frete ensinado pelo operador",
        **merged,
    }
    ARQUIVO_MEMORIA.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _cache_memoria = merged
    return novas


def consultar_memoria(
    observacao: str,
    descricao: str = "",
    memoria: Optional[dict[str, str]] = None,
) -> tuple[str, str] | None:
    """
    Busca status aprendido por texto da observação/descrição.
    Retorna (status, tipo_frete) ou None.
    """
    texto = normalizar_texto_memoria(observacao, descricao)
    if not texto:
        return None

    memoria = memoria if memoria is not None else carregar_memoria()

    if texto in memoria:
        status = memoria[texto].strip()
        tipo = STATUS_PARA_TIPO_FRETE.get(status, status)
        return status, tipo

    candidatos: list[tuple[int, str]] = []
    for chave, status in memoria.items():
        if len(chave) < 8:
            continue
        if chave in texto or texto in chave:
            candidatos.append((len(chave), status.strip()))

    if not candidatos:
        return None

    candidatos.sort(key=lambda x: x[0], reverse=True)
    status = candidatos[0][1]
    tipo = STATUS_PARA_TIPO_FRETE.get(status, status)
    return status, tipo


def montar_chave_memoria(observacao: str, descricao: str = "") -> str:
    return normalizar_texto_memoria(observacao, descricao)
