"""Consulta de pedidos arquivados."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Query

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import HistoricoRegistroSchema, HistoricoResponseSchema  # noqa: E402
from historico_manager import buscar_historico  # noqa: E402

router = APIRouter(prefix="/api/historico", tags=["historico"])


@router.get("", response_model=HistoricoResponseSchema)
def consultar_historico(
    q: str = Query("", description="Número do pedido ou nome do cliente"),
    tipo: str = Query("auto", description="auto | pedido | cliente"),
    limite: int = Query(50, ge=1, le=200),
) -> HistoricoResponseSchema:
    resultados = buscar_historico(q=q, tipo=tipo, limite=limite)
    return HistoricoResponseSchema(
        q=q,
        total=len(resultados),
        resultados=[
            HistoricoRegistroSchema(
                hash_id=r.get("hash_id", ""),
                numero_pedido=r.get("numero_pedido", ""),
                numero_pedido_norm=r.get("numero_pedido_norm", ""),
                cliente=r.get("cliente", ""),
                cliente_codigo=r.get("cliente_codigo", ""),
                status_final=r.get("status_final", ""),
                data_entrega=r.get("data_entrega", ""),
                data_arquivamento=r.get("data_arquivamento", ""),
                session_id=r.get("session_id", ""),
                arquivo_historico=r.get("arquivo_historico", ""),
            )
            for r in resultados
        ],
    )
