"""
Geocodificação via Nominatim (OpenStreetMap) — Fase A do Route Optimizer.

Respeita limite gratuito: User-Agent obrigatório + intervalo mínimo entre requisições.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from normalizador import normalizar_texto  # noqa: E402

_ultima_requisicao_nominatim: float = 0.0


def _parse_coord(valor: Any) -> float | None:
    if valor is None:
        return None
    texto = str(valor).strip().replace(",", ".")
    if not texto or texto.lower() in ("nan", "none", "null", ""):
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def coordenadas_preenchidas(dados: dict[str, Any]) -> bool:
    lat = _parse_coord(dados.get("latitude"))
    lon = _parse_coord(dados.get("longitude"))
    if lat is None or lon is None:
        return False
    if abs(lat) < 0.0001 and abs(lon) < 0.0001:
        return False
    return True


def _titulo(texto: str) -> str:
    t = normalizar_texto(texto)
    if not t:
        return ""
    return t.title()


def montar_endereco_completo(
    rua: str = "",
    numero: str = "",
    bairro: str = "",
    cidade: str = "",
    estado: str = "",
    cep: str = "",
) -> str:
    partes: list[str] = []
    rua_l = _titulo(rua)
    num = str(numero or "").strip()
    if rua_l and num:
        partes.append(f"{rua_l}, {num}")
    elif rua_l:
        partes.append(rua_l)
    if _titulo(bairro):
        partes.append(_titulo(bairro))
    if _titulo(cidade):
        partes.append(_titulo(cidade))
    if normalizar_texto(estado) and len(normalizar_texto(estado)) <= 3:
        partes.append(normalizar_texto(estado))
    cep_limpo = "".join(c for c in str(cep or "") if c.isdigit())
    if cep_limpo:
        partes.append(cep_limpo)
    if partes:
        partes.append("Brasil")
    return ", ".join(partes)


def _montar_query_cidade_cep(cidade: str, cep: str) -> str:
    partes: list[str] = []
    if _titulo(cidade):
        partes.append(_titulo(cidade))
    cep_limpo = "".join(c for c in str(cep or "") if c.isdigit())
    if cep_limpo:
        partes.append(cep_limpo)
    if not partes:
        return ""
    partes.append("Brasil")
    return ", ".join(partes)


def _montar_query_cidade_estado(cidade: str, estado: str) -> str:
    partes: list[str] = []
    if _titulo(cidade):
        partes.append(_titulo(cidade))
    uf = normalizar_texto(estado)
    if uf and len(uf) <= 3:
        partes.append(uf)
    if not partes:
        return ""
    partes.append("Brasil")
    return ", ".join(partes)


def _aguardar_intervalo_nominatim() -> None:
    global _ultima_requisicao_nominatim
    agora = time.time()
    if _ultima_requisicao_nominatim > 0:
        decorrido = agora - _ultima_requisicao_nominatim
        if decorrido < config.NOMINATIM_INTERVALO_SEG:
            time.sleep(config.NOMINATIM_INTERVALO_SEG - decorrido)
    _ultima_requisicao_nominatim = time.time()


def geocodificar_endereco(endereco_formatado: str) -> tuple[float, float] | None:
    """Consulta Nominatim e retorna (latitude, longitude) ou None."""
    query = (endereco_formatado or "").strip()
    if not query:
        return None

    _aguardar_intervalo_nominatim()

    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "limit": 1,
            "countrycodes": "br",
        }
    )
    url = f"{config.NOMINATIM_URL}?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": config.NOMINATIM_USER_AGENT},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None

    if not payload or not isinstance(payload, list):
        return None

    hit = payload[0]
    lat = _parse_coord(hit.get("lat"))
    lon = _parse_coord(hit.get("lon"))
    if lat is None or lon is None:
        return None
    return lat, lon


def geocodificar_campos(
    rua: str = "",
    numero: str = "",
    bairro: str = "",
    cidade: str = "",
    estado: str = "",
    cep: str = "",
    *,
    usar_rede: bool = True,
) -> dict[str, float | None]:
    """
    Geocodifica endereço com fallback:
    1) Endereço completo (Rua, Número, Bairro, Cidade, Estado, CEP)
    2) Cidade + CEP
    3) Cidade + Estado
    """
    if not usar_rede:
        return {"latitude": None, "longitude": None}

    queries = [
        montar_endereco_completo(rua, numero, bairro, cidade, estado, cep),
        _montar_query_cidade_cep(cidade, cep),
        _montar_query_cidade_estado(cidade, estado),
    ]

    vistos: set[str] = set()
    for query in queries:
        if not query or query in vistos:
            continue
        vistos.add(query)
        coords = geocodificar_endereco(query)
        if coords:
            return {"latitude": coords[0], "longitude": coords[1]}

    return {"latitude": None, "longitude": None}


def montar_query_endereco(dados: dict[str, Any]) -> str:
    """Compatibilidade — monta query a partir de dict genérico."""
    return montar_endereco_completo(
        rua=str(dados.get("rua") or dados.get("endereco") or ""),
        numero=str(dados.get("numero") or ""),
        bairro=str(dados.get("bairro") or dados.get("bairro_destino") or ""),
        cidade=str(dados.get("cidade") or dados.get("cidade_destino") or ""),
        estado=str(dados.get("estado") or dados.get("estado_destino") or dados.get("uf") or ""),
        cep=str(dados.get("cep") or dados.get("cep_destino") or ""),
    )
