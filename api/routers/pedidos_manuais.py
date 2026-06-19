"""Entrada manual de pedidos fora do PDF."""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from api.schemas import (  # noqa: E402
    PedidoConsolidadoSchema,
    PedidoManualBodySchema,
    PedidoManualResponseSchema,
)
from api.session_store import SessionNotFoundError, store  # noqa: E402
from historico_manager import hash_pedido, pedido_existe_no_historico  # noqa: E402
from models import PedidoConsolidado  # noqa: E402
from motor_ingestao import MotorIngestao  # noqa: E402
from normalizador import normalizar_pedido, normalizar_texto, resolver_rota_logistica  # noqa: E402
from param_manager import carregar_parametros  # noqa: E402

router = APIRouter(prefix="/api/pedidos-manuais", tags=["pedidos-manuais"])


def _dict_to_consolidado(data: dict) -> PedidoConsolidado:
    return PedidoConsolidado(**{k: data.get(k, "") for k in PedidoConsolidado.__dataclass_fields__})


@router.post("", response_model=PedidoManualResponseSchema)
def criar_pedido_manual(body: PedidoManualBodySchema) -> PedidoManualResponseSchema:
    try:
        store.session_path(body.session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    if store.is_validated(body.session_id):
        raise HTTPException(status_code=409, detail="Sessão já validada — use nova sessão.")

    ingest = store.load_ingestao(body.session_id)
    if not ingest:
        ingest = {
            "resumo": MotorIngestao(str(store.session_path(body.session_id))).resumo(),
            "consolidados": [],
            "avisos": [],
        }

    numero_norm = normalizar_pedido(body.numero_pedido)
    h_id = hash_pedido(numero_norm or body.numero_pedido, body.cliente_codigo)

    for item in ingest.get("consolidados", []):
        if item.get("numero_pedido_norm") == numero_norm or item.get("hash_id") == h_id:
            return PedidoManualResponseSchema(
                ok=False,
                session_id=body.session_id,
                numero_pedido=body.numero_pedido,
                hash_id=h_id,
                message="Pedido já existe na sessão atual.",
                ignorado_duplicata=True,
            )

    if pedido_existe_no_historico(numero_norm or body.numero_pedido, body.cliente_codigo):
        return PedidoManualResponseSchema(
            ok=False,
            session_id=body.session_id,
            numero_pedido=body.numero_pedido,
            hash_id=h_id,
            message="Pedido ignorado — já consta no histórico.",
            ignorado_duplicata=True,
        )

    params = carregar_parametros()
    cidade = normalizar_texto(body.cidade)
    status = normalizar_texto(body.status)
    if status in ("RETIRA_FOB", "RETIRA FOB"):
        status = config.COD_RETIRA_FOB
    elif status == "LIBERADO":
        status = config.COD_LIBERADO
    elif status == "ENTREGA_TERCEIRO_HUB":
        status = config.COD_TERCEIRO_HUB

    item = PedidoConsolidado(
        numero_pedido=body.numero_pedido.strip(),
        numero_pedido_norm=numero_norm,
        cliente=body.cliente.strip(),
        cliente_codigo=body.cliente_codigo.strip(),
        peso_kg=float(body.peso_kg),
        valor_tt=float(body.valor_tt),
        cidade=cidade,
        cidade_destino=cidade,
        bairro=normalizar_texto(body.bairro),
        bairro_destino=normalizar_texto(body.bairro),
        cep=body.cep.strip(),
        cep_destino=body.cep.strip(),
        representante=body.representante or "NÃO IDENTIFICADO",
        rota_logistica=resolver_rota_logistica(cidade, params),
        status=status,
        tipo_frete="ENTREGA_DIRETA" if status == config.COD_LIBERADO else "",
        fontes="MANUAL",
        fonte_entrada="MANUAL",
        observacao_comercial=body.observacao_comercial,
        hash_id=h_id,
        data_prevista_recebimento=body.data_prevista_recebimento.strip(),
        motivo_atraso=body.motivo_atraso.strip(),
        auditoria="ENTRADA MANUAL",
    )

    ingest.setdefault("consolidados", []).append(asdict(item))

    motor = MotorIngestao(str(store.session_path(body.session_id)))
    motor.consolidados = [_dict_to_consolidado(c) for c in ingest["consolidados"]]
    ingest["resumo"] = motor.resumo()
    store.save_ingestao(body.session_id, ingest)

    return PedidoManualResponseSchema(
        ok=True,
        session_id=body.session_id,
        numero_pedido=body.numero_pedido,
        hash_id=h_id,
        message="Pedido manual incluído na sessão.",
    )


@router.post("/{session_id}", response_model=PedidoConsolidadoSchema, deprecated=True)
def criar_pedido_manual_legacy(session_id: str, body: PedidoManualBodySchema) -> PedidoConsolidadoSchema:
    body.session_id = session_id
    resp = criar_pedido_manual(body)
    if not resp.ok:
        raise HTTPException(status_code=409, detail=resp.message)
    ingest = store.load_ingestao(session_id)
    for c in ingest.get("consolidados", []):
        if c.get("numero_pedido") == body.numero_pedido:
            return PedidoConsolidadoSchema(**c)
    raise HTTPException(status_code=500, detail="Pedido criado mas não encontrado.")
