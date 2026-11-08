"""
Cadastro mestre geolocalizado — JSON unificado (clientes + transportadoras).
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import config
from normalizador import normalizar_codigo_cliente, normalizar_texto

PROJECT_ROOT = Path(__file__).resolve().parent
_cache: dict[str, Any] | None = None


def caminho_cadastro_geolocalizado() -> Path:
    return PROJECT_ROOT / config.ARQUIVO_CADASTRO_GEOLOCALIZADO


def _limpar_cnpj(valor: str) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def coordenadas_validas(lat: Any, lon: Any) -> bool:
    try:
        la = float(str(lat).replace(",", "."))
        lo = float(str(lon).replace(",", "."))
    except (TypeError, ValueError):
        return False
    if abs(la) < 0.0001 and abs(lo) < 0.0001:
        return False
    return -90 <= la <= 90 and -180 <= lo <= 180


def carregar_cadastro_geolocalizado(recarregar: bool = False) -> dict[str, Any]:
    global _cache
    if _cache is not None and not recarregar:
        return deepcopy(_cache)

    path = caminho_cadastro_geolocalizado()
    if not path.is_file():
        payload: dict[str, Any] = {
            "_versao": "1",
            "_gerado_em": "",
            "registros": [],
            "indice_por_codigo": {},
            "indice_por_cnpj": {},
        }
        _cache = payload
        return deepcopy(_cache)

    bruto = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(bruto, dict):
        bruto = {"registros": bruto if isinstance(bruto, list) else []}

    registros = bruto.get("registros") or []
    indice_codigo: dict[str, dict[str, Any]] = {}
    indice_cnpj: dict[str, dict[str, Any]] = {}

    for reg in registros:
        if not isinstance(reg, dict):
            continue
        codigo = normalizar_codigo_cliente(str(reg.get("codigo") or ""))
        if codigo:
            indice_codigo[codigo] = reg
        cnpj = _limpar_cnpj(str(reg.get("cnpj") or reg.get("id_cnpj") or ""))
        if cnpj:
            indice_cnpj[cnpj] = reg

    bruto["indice_por_codigo"] = indice_codigo
    bruto["indice_por_cnpj"] = indice_cnpj
    _cache = bruto
    return deepcopy(_cache)


def invalidar_cache_geolocalizado() -> None:
    global _cache
    _cache = None


def salvar_cadastro_geolocalizado(registros: list[dict[str, Any]]) -> str:
    global _cache
    path = caminho_cadastro_geolocalizado()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "_versao": "1",
        "_gerado_em": date.today().isoformat(),
        "registros": registros,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    invalidar_cache_geolocalizado()
    return str(path)


def buscar_por_codigo_cliente(codigo: str, dados: dict[str, Any] | None = None) -> dict[str, Any] | None:
    dados = dados or carregar_cadastro_geolocalizado()
    chave = normalizar_codigo_cliente(codigo)
    if not chave:
        return None
    return (dados.get("indice_por_codigo") or {}).get(chave)


def buscar_por_cidade(cidade: str, dados: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    dados = dados or carregar_cadastro_geolocalizado()
    alvo = normalizar_texto(cidade)
    if not alvo:
        return []
    return [
        r
        for r in (dados.get("registros") or [])
        if normalizar_texto(str(r.get("cidade") or "")) == alvo
    ]
