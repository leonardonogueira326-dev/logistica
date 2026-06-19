"""
Gestão histórica — arquivamento, idempotência e consulta de pedidos.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from normalizador import normalizar_cliente, normalizar_pedido

PROJECT_ROOT = Path(__file__).resolve().parent
HISTORICO_DIR = PROJECT_ROOT / "data" / "historico"

_cache_hashes: set[str] | None = None


def hash_pedido(numero_pedido: str, cliente_codigo: str = "") -> str:
    """ID único estável para idempotência."""
    chave = f"{normalizar_pedido(numero_pedido)}|{cliente_codigo.strip()}".upper()
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()[:16]


def _arquivo_historico(data_ref: date | None = None) -> Path:
    data_ref = data_ref or date.today()
    return HISTORICO_DIR / f"ingestao_{data_ref.isoformat()}.json"


def _carregar_arquivo(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"pedidos": {}, "indice_pedido": {}, "indice_cliente": {}}
    try:
        bruto = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(bruto, dict):
            bruto.setdefault("pedidos", {})
            bruto.setdefault("indice_pedido", {})
            bruto.setdefault("indice_cliente", {})
            return bruto
    except Exception:
        pass
    return {"pedidos": {}, "indice_pedido": {}, "indice_cliente": {}}


def _salvar_arquivo(path: Path, payload: dict[str, Any]) -> None:
    HISTORICO_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _rebuild_cache_hashes() -> set[str]:
    hashes: set[str] = set()
    if not HISTORICO_DIR.exists():
        return hashes
    for arquivo in HISTORICO_DIR.glob("ingestao_*.json"):
        data = _carregar_arquivo(arquivo)
        hashes.update(data.get("pedidos", {}).keys())
    return hashes


def carregar_hashes_historico(recarregar: bool = False) -> set[str]:
    global _cache_hashes
    if _cache_hashes is None or recarregar:
        _cache_hashes = _rebuild_cache_hashes()
    return _cache_hashes


def pedido_existe_no_historico(numero_pedido: str, cliente_codigo: str = "") -> bool:
    h = hash_pedido(numero_pedido, cliente_codigo)
    return h in carregar_hashes_historico()


def arquivar_sessao(
    session_id: str,
    consolidados: list[dict[str, Any]],
    data_ref: date | None = None,
    data_entrega: str = "",
) -> str:
    """Move/consolida pedidos da sessão para data/historico/ingestao_{data}.json."""
    data_ref = data_ref or date.today()
    path = _arquivo_historico(data_ref)
    payload = _carregar_arquivo(path)
    payload.setdefault("data_arquivo", data_ref.isoformat())
    payload.setdefault("sessoes", [])
    if session_id not in payload["sessoes"]:
        payload["sessoes"].append(session_id)

    data_entrega = data_entrega or data_ref.isoformat()
    for item in consolidados:
        h = hash_pedido(
            item.get("numero_pedido_norm") or item.get("numero_pedido", ""),
            item.get("cliente_codigo", ""),
        )
        registro = {
            "hash_id": h,
            "numero_pedido": item.get("numero_pedido", ""),
            "numero_pedido_norm": item.get("numero_pedido_norm", ""),
            "cliente": item.get("cliente", ""),
            "cliente_codigo": item.get("cliente_codigo", ""),
            "status_final": item.get("status", ""),
            "data_entrega": data_entrega,
            "data_arquivamento": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "consolidado": item,
        }
        payload["pedidos"][h] = registro
        np = normalizar_pedido(item.get("numero_pedido_norm") or item.get("numero_pedido", ""))
        if np:
            payload["indice_pedido"][np] = h
        cliente_norm = normalizar_cliente(item.get("cliente", ""))
        if cliente_norm:
            payload["indice_cliente"].setdefault(cliente_norm, [])
            if h not in payload["indice_cliente"][cliente_norm]:
                payload["indice_cliente"][cliente_norm].append(h)

    _salvar_arquivo(path, payload)
    carregar_hashes_historico(recarregar=True)
    return str(path)


def buscar_historico(
    q: str = "",
    tipo: str = "auto",
    limite: int = 50,
) -> list[dict[str, Any]]:
    """Pesquisa pedidos arquivados por número ou cliente."""
    q = (q or "").strip()
    if not q:
        return []

    resultados: list[dict[str, Any]] = []
    vistos: set[str] = set()
    q_upper = q.upper()
    q_norm_pedido = normalizar_pedido(q)
    q_norm_cliente = normalizar_cliente(q)

    if not HISTORICO_DIR.exists():
        return []

    for arquivo in sorted(HISTORICO_DIR.glob("ingestao_*.json"), reverse=True):
        data = _carregar_arquivo(arquivo)
        pedidos = data.get("pedidos", {})
        indice_pedido = data.get("indice_pedido", {})
        indice_cliente = data.get("indice_cliente", {})

        candidatos: set[str] = set()
        if tipo in ("auto", "pedido"):
            if q_norm_pedido in indice_pedido:
                candidatos.add(indice_pedido[q_norm_pedido])
            for np, h in indice_pedido.items():
                if q_upper in np or q in np:
                    candidatos.add(h)
        if tipo in ("auto", "cliente"):
            if q_norm_cliente in indice_cliente:
                candidatos.update(indice_cliente[q_norm_cliente])
            for cli, hashes in indice_cliente.items():
                if q_norm_cliente in cli or q_upper in cli.upper():
                    candidatos.update(hashes)

        for h in candidatos:
            if h in vistos:
                continue
            reg = pedidos.get(h)
            if reg:
                reg = {**reg, "arquivo_historico": arquivo.name}
                resultados.append(reg)
                vistos.add(h)
            if len(resultados) >= limite:
                return resultados

    return resultados[:limite]
