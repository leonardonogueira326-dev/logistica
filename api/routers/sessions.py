"""Endpoints de sessão — upload, ingestão, validação e roteirização."""

from __future__ import annotations

from io import BytesIO
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import (  # noqa: E402
    ConsolidadoPatchSchema,
    ConsolidadosListSchema,
    IngestaoResponseSchema,
    MoverPedidoSchema,
    MoverPedidoResponseSchema,
    PedidoConsolidadoSchema,
    ResumoIngestaoSchema,
    RoteirizacaoSchema,
    UploadResponseSchema,
    ValidacaoConfirmarSchema,
    ValidacaoConfirmarBodySchema,
)
from api.session_store import SessionNotFoundError, store  # noqa: E402
from aprendizado_regras import salvar_regras  # noqa: E402
from models import PedidoConsolidado  # noqa: E402
from motor_ingestao import MotorIngestao  # noqa: E402
from motor_logistica import MotorLogistica  # noqa: E402
import config  # noqa: E402
from normalizador import normalizar_texto, resolver_rota_logistica  # noqa: E402
from param_manager import carregar_parametros  # noqa: E402
from gerador_romaneio import gerar_romaneio_xlsx, nome_arquivo_romaneio  # noqa: E402

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

UPLOAD_FIELDS = {
    "pdf": (".pdf",),
    "xlsb": (".xlsb", ".xlsx"),
    "msg": (".msg",),
}


def _dict_to_consolidado(data: dict[str, Any]) -> PedidoConsolidado:
    return PedidoConsolidado(**{k: data.get(k, "") for k in PedidoConsolidado.__dataclass_fields__})


def _consolidados_from_ingestao(data: dict[str, Any]) -> list[PedidoConsolidado]:
    return [_dict_to_consolidado(c) for c in data.get("consolidados", [])]


def _get_active_consolidados(session_id: str) -> tuple[dict[str, Any], list[PedidoConsolidado], bool]:
    validated = store.is_validated(session_id)
    if validated:
        val_data = store.load_consolidados_validados(session_id)
        if val_data:
            return val_data, [_dict_to_consolidado(c) for c in val_data.get("consolidados", [])], True

    ingest = store.load_ingestao(session_id)
    if not ingest:
        raise HTTPException(status_code=404, detail="Ingestão não executada para esta sessão.")
    return ingest, _consolidados_from_ingestao(ingest), False


def _roteirizacao_from_motor(motor: MotorLogistica, session_id: str) -> RoteirizacaoSchema:
    data = motor.para_dict()
    params = carregar_parametros()
    return RoteirizacaoSchema(
        session_id=session_id,
        rotas=data["rotas"],
        itens_por_veiculo=data["itens_por_veiculo"],
        backlog=data["backlog"],
        coletas=data.get("coletas", []),
        jornada_maxima_minutos=int(params.get("jornada_maxima_minutos", 600)),
    )


@router.post("/upload", response_model=UploadResponseSchema)
async def upload_session(
    pdf: Optional[UploadFile] = File(None),
    xlsb: Optional[UploadFile] = File(None),
    msg: Optional[UploadFile] = File(None),
) -> UploadResponseSchema:
    session_id = store.create_session()
    saved: list[str] = []
    warnings: list[str] = []

    for field_name, upload in [("pdf", pdf), ("xlsb", xlsb), ("msg", msg)]:
        if upload is None or not upload.filename:
            continue
        content = await upload.read()
        if not content:
            warnings.append(f"Arquivo {field_name} vazio — ignorado.")
            continue
        dest = store.save_upload(session_id, upload.filename, content)
        saved.append(dest.name)

    if not saved:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    return UploadResponseSchema(session_id=session_id, files_saved=saved, warnings=warnings)


@router.post("/{session_id}/ingest", response_model=IngestaoResponseSchema)
def ingest_session(session_id: str) -> IngestaoResponseSchema:
    try:
        session_dir = store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    uploads = store.uploads_dir(session_id)
    motor = MotorIngestao(str(session_dir))
    motor.executar(
        caminho_pdf=_find_file(uploads, UPLOAD_FIELDS["pdf"]),
        caminho_xlsb=_find_file(uploads, UPLOAD_FIELDS["xlsb"]),
        caminho_msg=_find_file(uploads, UPLOAD_FIELDS["msg"]),
    )

    payload = motor.para_dict()
    store.save_ingestao(session_id, payload)

    return IngestaoResponseSchema(
        session_id=session_id,
        resumo=ResumoIngestaoSchema(**payload["resumo"]),
        consolidados=[PedidoConsolidadoSchema(**c) for c in payload["consolidados"]],
        avisos=motor.avisos,
        erros=motor.erros,
    )


@router.get("/{session_id}/consolidados", response_model=ConsolidadosListSchema)
def list_consolidados(session_id: str) -> ConsolidadosListSchema:
    try:
        data, consolidados, validated = _get_active_consolidados(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    resumo = None
    if "resumo" in data:
        resumo = ResumoIngestaoSchema(**data["resumo"])

    avisos = data.get("avisos", [])
    if isinstance(avisos, str):
        avisos = [avisos] if avisos and avisos != "NENHUM" else []

    return ConsolidadosListSchema(
        session_id=session_id,
        validated=validated,
        resumo=resumo,
        consolidados=[PedidoConsolidadoSchema(**asdict(c)) for c in consolidados],
        avisos=avisos if isinstance(avisos, list) else [],
    )


@router.patch("/{session_id}/consolidados/{pedido_norm:path}", response_model=PedidoConsolidadoSchema)
def patch_consolidado(
    session_id: str,
    pedido_norm: str,
    patch: ConsolidadoPatchSchema,
) -> PedidoConsolidadoSchema:
    if store.is_validated(session_id):
        raise HTTPException(status_code=409, detail="Sessão já validada — edição bloqueada.")

    ingest = store.load_ingestao(session_id)
    if not ingest:
        raise HTTPException(status_code=404, detail="Ingestão não executada.")

    params = carregar_parametros()
    found_idx = -1
    for i, raw in enumerate(ingest.get("consolidados", [])):
        if raw.get("numero_pedido_norm") == pedido_norm or raw.get("numero_pedido") == pedido_norm:
            found_idx = i
            break

    if found_idx < 0:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_norm} não encontrado.")

    item = ingest["consolidados"][found_idx]
    updates = patch.model_dump(exclude_none=True)

    for key, value in updates.items():
        item[key] = value
        if key in ("bairro", "cidade", "cep"):
            dest_key = f"{key}_destino" if key != "cep" else "cep_destino"
            item[dest_key] = value

    if "status" in updates:
        status = normalizar_texto(updates["status"])
        if status in ("RETIRA_FOB",):
            status = config.COD_RETIRA_FOB
        item["status"] = status
        tipo_map = {
            config.COD_LIBERADO: "ENTREGA_DIRETA",
            config.COD_RETIRA_FOB: "RETIRA_FOB",
            config.COD_TERCEIRO_HUB: "ENTREGA_TERCEIRO_HUB",
            config.COD_BLOQUEIO_FISCAL: "",
        }
        if status in tipo_map:
            item["tipo_frete"] = tipo_map[status]
        item["auditoria"] = (
            (item.get("auditoria", "") + " | STATUS AJUSTADO NA VALIDAÇÃO").strip(" |")
        )

    if "cidade" in updates:
        cidade = normalizar_texto(item.get("cidade_destino") or item.get("cidade", ""))
        item["rota_logistica"] = resolver_rota_logistica(cidade, params)
        item["auditoria"] = (item.get("auditoria", "") + " | ROTA RECALCULADA NA VALIDAÇÃO").strip(" |")

    store.save_ingestao(session_id, ingest)
    return PedidoConsolidadoSchema(**item)


@router.post("/{session_id}/validacao/confirmar", response_model=ValidacaoConfirmarSchema)
def confirmar_validacao(
    session_id: str,
    body: ValidacaoConfirmarBodySchema | None = None,
) -> ValidacaoConfirmarSchema:
    try:
        ingest = store.load_ingestao(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    if not ingest:
        raise HTTPException(status_code=404, detail="Ingestão não executada.")

    regras_salvas = 0
    if body and body.regras_novas:
        regras_validas: dict[str, str] = {}
        for chave, status in body.regras_novas.items():
            if chave.startswith("_") or not status:
                continue
            regras_validas[str(chave)] = str(status)
        if regras_validas:
            regras_salvas = salvar_regras(regras_validas)

    if store.is_validated(session_id):
        total = len(ingest.get("consolidados", []))
        return ValidacaoConfirmarSchema(
            session_id=session_id,
            validated=True,
            total_consolidados=total,
            regras_salvas=regras_salvas,
            message="Validação já confirmada anteriormente.",
        )

    payload = {
        "resumo": ingest.get("resumo", {}),
        "consolidados": ingest.get("consolidados", []),
        "validated_at": store.get_meta(session_id).get("validated_at"),
    }
    store.save_consolidados_validados(session_id, payload)
    store.set_validated(session_id, True)

    total = len(payload["consolidados"])
    msg = f"Validação confirmada — {total} pedidos prontos para roteirização."
    if regras_salvas:
        msg += f" {regras_salvas} regra(s) salva(s) no aprendizado local."
    return ValidacaoConfirmarSchema(
        session_id=session_id,
        validated=True,
        total_consolidados=total,
        regras_salvas=regras_salvas,
        message=msg,
    )


@router.post("/{session_id}/roteirizar", response_model=RoteirizacaoSchema)
def roteirizar(session_id: str) -> RoteirizacaoSchema:
    try:
        _, consolidados, _ = _get_active_consolidados(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    except HTTPException:
        raise

    motor = MotorLogistica()
    motor.alocar_frota(consolidados)
    payload = motor.para_dict()
    store.save_roteirizacao(session_id, payload)
    return _roteirizacao_from_motor(motor, session_id)


@router.get("/{session_id}/roteirizacao", response_model=RoteirizacaoSchema)
def get_roteirizacao(session_id: str) -> RoteirizacaoSchema:
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    data.setdefault("coletas", [])
    params = carregar_parametros()
    return RoteirizacaoSchema(
        session_id=session_id,
        jornada_maxima_minutos=int(params.get("jornada_maxima_minutos", 600)),
        **data,
    )


@router.get("/{session_id}/exportar-romaneio")
def exportar_romaneio(session_id: str) -> StreamingResponse:
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    try:
        conteudo = gerar_romaneio_xlsx(data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao gerar romaneio: {exc}") from exc

    filename = nome_arquivo_romaneio(session_id)
    return StreamingResponse(
        BytesIO(conteudo),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{session_id}/mover", response_model=MoverPedidoResponseSchema)
def mover_pedido(session_id: str, body: MoverPedidoSchema) -> MoverPedidoResponseSchema:
    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    motor = MotorLogistica()
    motor.rotas = [_dict_to_rota(r) for r in data.get("rotas", [])]
    motor.itens_por_veiculo = {
        vid: [_dict_to_item(i) for i in itens]
        for vid, itens in data.get("itens_por_veiculo", {}).items()
    }
    motor.backlog = data.get("backlog", [])
    motor.coletas = data.get("coletas", [])

    ok, warning = motor.mover_pedido(
        body.numero_pedido,
        body.destino,
        body.motivo,
        forcar=body.forcar,
    )

    if not ok:
        raise HTTPException(status_code=400, detail=warning or "Não foi possível mover o pedido.")

    payload = motor.para_dict()
    store.save_roteirizacao(session_id, payload)
    return MoverPedidoResponseSchema(
        ok=True,
        warning=warning,
        roteirizacao=_roteirizacao_from_motor(motor, session_id),
    )


def _find_file(folder: Path, extensions: tuple[str, ...]) -> str:
    for ext in extensions:
        matches = sorted(folder.glob(f"*{ext}"))
        if matches:
            return str(matches[0])
    return ""


def _dict_to_rota(data: dict[str, Any]):
    from models import RotaVeiculo

    return RotaVeiculo(**{k: data.get(k, "") for k in RotaVeiculo.__dataclass_fields__})


def _dict_to_item(data: dict[str, Any]):
    from models import ItemRota

    return ItemRota(**{k: data.get(k, "") for k in ItemRota.__dataclass_fields__})
