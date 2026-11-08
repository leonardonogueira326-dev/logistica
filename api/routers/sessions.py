"""Endpoints de sessão — upload, ingestão, validação e roteirização."""

from __future__ import annotations

from io import BytesIO
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import (  # noqa: E402
    AnteciparPedidoBodySchema,
    AnteciparPedidoResponseSchema,
    ConsolidadoPatchSchema,
    ConsolidadosListSchema,
    IngestaoResponseSchema,
    AjustarDivisaoSchema,
    CargaRefSchema,
    ConsultaRepresentanteBodySchema,
    InformarPesoBodySchema,
    LiberacaoComercialBodySchema,
    ConsultaRepresentanteResponseSchema,
    DividirCargaSchema,
    EquipeVeiculoSchema,
    FecharVeiculoSchema,
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
from api.ia_worker import processar_fila_llm, tem_pendentes_ia  # noqa: E402
from aprendizado_regras import salvar_regras  # noqa: E402
from memoria_operacional import salvar_memoria  # noqa: E402
from models import PedidoConsolidado  # noqa: E402
from motor_ingestao import MotorIngestao  # noqa: E402
from motor_logistica import MotorLogistica  # noqa: E402
import config  # noqa: E402
from normalizador import formatar_kg, mesma_linha, normalizar_texto, resolver_rota_logistica  # noqa: E402
from pendencias import motivo_parado, pendencias as calc_pendencias  # noqa: E402
from representantes import aprender_representante  # noqa: E402
from equipe import equipe_inicial, frota_cadastrada, lembrar  # noqa: E402
from romaneio_planilha import gerar_romaneio_planilha  # noqa: E402
from param_manager import carregar_parametros  # noqa: E402
from gerador_romaneio import (  # noqa: E402
    gerar_romaneio_caminhao_xlsx,
    gerar_romaneio_xlsx,
    nome_arquivo_romaneio,
    nome_arquivo_romaneio_caminhao,
)
from historico_manager import arquivar_sessao, chave_linha_solicitacao  # noqa: E402

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

UPLOAD_FIELDS = {
    "pdf": (".pdf",),
    "xlsb": (".xlsb", ".xlsx"),
    "msg": (".msg",),
}


def _dict_to_consolidado(data: dict[str, Any]) -> PedidoConsolidado:
    fields = PedidoConsolidado.__dataclass_fields__
    return PedidoConsolidado(
        **{k: data.get(k, fields[k].default) for k in fields}
    )


def _consolidados_from_ingestao(data: dict[str, Any]) -> list[PedidoConsolidado]:
    return [_dict_to_consolidado(c) for c in data.get("consolidados", [])]


def _limite_consulta() -> int:
    return int(carregar_parametros().get("antecedencia_consulta_dias_uteis", 3))


def _consolidado_com_pendencias(c: PedidoConsolidado, limite: int | None = None) -> PedidoConsolidadoSchema:
    limite = _limite_consulta() if limite is None else limite
    return PedidoConsolidadoSchema(
        **asdict(c), pendencias=calc_pendencias(c, limite), motivo_parado=motivo_parado(c, limite)
    )


def _nomes_veiculos(motor: MotorLogistica) -> dict[str, str]:
    """Nome para mensagens; desambigua quando dois caminhões têm o mesmo nome."""
    contagem: dict[str, int] = {}
    for r in motor.rotas:
        contagem[r.veiculo_nome] = contagem.get(r.veiculo_nome, 0) + 1
    return {
        r.veiculo_id: (r.veiculo_nome if contagem[r.veiculo_nome] == 1 else f"{r.veiculo_nome} ({r.veiculo_id})")
        for r in motor.rotas
    }


def _alocar_resolvidos(session_id: str, ids: list[str]) -> dict[str, str]:
    """
    Mantém o quadro em dia sem roteirizar de novo:
    - linha que ficou SEM pendência entra na rota (caminhão compatível e aberto,
      ou fila de hoje);
    - linha que voltou a ter pendência e está num caminhão sai para "Parados".
    Retorna {id: destino} (destino começa com "↩" quando a linha saiu).
    """
    rote_data = store.load_roteirizacao(session_id)
    if not rote_data or not ids:
        return {}
    _, consolidados, _ = _get_active_consolidados(session_id)
    limite = _limite_consulta()
    motor = _motor_from_roteirizacao(rote_data)
    nomes = _nomes_veiculos(motor)
    resultado: dict[str, str] = {}
    for id_linha in ids:
        c = next((x for x in consolidados if mesma_linha(x, id_linha)), None)
        if not c:
            continue
        motivo = motivo_parado(c, limite)
        if motivo:
            antes = {vid for vid, itens in motor.itens_por_veiculo.items()
                     if any((i.id_item or i.numero_pedido) == (c.id_item or id_linha) for i in itens)}
            if motor.tirar_do_caminhao_por_pendencia(c.id_item or id_linha, motivo):
                resultado[id_linha] = "↩" + ", ".join(nomes.get(v, v) for v in sorted(antes))
            continue
        for entry in motor.backlog_futuro:
            if mesma_linha(entry, id_linha):
                entry["peso_kg"] = str(c.peso_kg)  # peso pode ter sido informado agora
                entry["pendencias"] = ""
        ok, _, destino = motor.antecipar_para_hoje(c.id_item or id_linha)
        if ok:
            resultado[id_linha] = nomes.get(destino, "fila de hoje")
    store.save_roteirizacao(session_id, motor.para_dict())
    return resultado


def _resumo_sincronizacao(alocados: dict[str, str]) -> str:
    entraram = sorted({d for d in alocados.values() if not d.startswith("↩")})
    sairam = sorted({d[1:] for d in alocados.values() if d.startswith("↩")})
    partes = []
    if entraram:
        partes.append("Entraram na rota: " + ", ".join(entraram) + ".")
    if sairam:
        partes.append("Saíram do caminhão e voltaram para Parados (" + ", ".join(sairam) + ").")
    return " ".join(partes)


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


def _roteirizacao_from_motor(
    motor: MotorLogistica, session_id: str, mensagem: str = ""
) -> RoteirizacaoSchema:
    data = motor.para_dict()
    params = carregar_parametros()
    return RoteirizacaoSchema(
        session_id=session_id,
        jornada_maxima_minutos=int(params.get("jornada_maxima_minutos", 600)),
        mensagem=mensagem,
        **data,
    )


def _motor_from_roteirizacao(data: dict[str, Any]) -> MotorLogistica:
    motor = MotorLogistica()
    motor.rotas = [_dict_to_rota(r) for r in data.get("rotas", [])]
    motor.itens_por_veiculo = {
        vid: [_dict_to_item(i) for i in itens]
        for vid, itens in data.get("itens_por_veiculo", {}).items()
    }
    motor.backlog = data.get("backlog", [])
    motor.backlog_futuro = data.get("backlog_futuro", [])
    motor.backlog_local = data.get("backlog_local", [])
    motor.coletas = data.get("coletas", [])
    motor.itens_retorno_por_veiculo = {
        vid: [_dict_to_item(i) for i in itens]
        for vid, itens in data.get("itens_retorno_por_veiculo", {}).items()
    }
    motor.viagens_retorno_habilitadas = list(data.get("viagens_retorno_habilitadas", []))
    motor.veiculos_fechados = list(data.get("veiculos_fechados", []))
    motor.equipe_por_veiculo = dict(data.get("equipe_por_veiculo", {}))
    return motor


def _enriquecer_teo_motor(motor: MotorLogistica) -> None:
    for vid in list(motor.itens_por_veiculo.keys()):
        motor.recalcular_metricas(vid)
    for rota in motor.rotas:
        if rota.veiculo_id not in motor.itens_por_veiculo:
            motor._aplicar_alertas_rota(rota, [])


def _patch_consolidado_session(session_id: str, numero_pedido: str, patch: dict[str, Any]) -> bool:
    """Atualiza pedido em ingestao ou consolidados validados."""
    validated = store.is_validated(session_id)
    if validated:
        data = store.load_consolidados_validados(session_id)
        fname = "consolidados_validados"
    else:
        data = store.load_ingestao(session_id)
        fname = "ingestao"

    if not data:
        return False

    found = False
    for item in data.get("consolidados", []):
        if mesma_linha(item, numero_pedido):
            item.update(patch)
            found = True
            break

    if not found:
        return False

    if validated:
        store.save_consolidados_validados(session_id, data)
    else:
        store.save_ingestao(session_id, data)
    return True


@router.post("/upload", response_model=UploadResponseSchema)
async def upload_session(
    pdf: Optional[UploadFile] = File(None),
    xlsb: Optional[UploadFile] = File(None),
    msg: Optional[UploadFile] = File(None),
    session_id: Optional[str] = Form(None, description="Adicionar ao quadro do dia desta sessão"),
) -> UploadResponseSchema:
    """
    Sem session_id: começa um dia novo. Com session_id: a lista entra no MESMO
    quadro (ex.: segunda lista do dia ou um adicional) sem mexer no que já foi
    montado.
    """
    adicionado = False
    if session_id:
        try:
            store.session_path(session_id)
            adicionado = True
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="Quadro do dia não encontrado.")
    else:
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
        nome = upload.filename
        if adicionado and (store.uploads_dir(session_id) / nome).exists():
            nome = f"{datetime.now().strftime('%H%M%S')}_{nome}"
        dest = store.save_upload(session_id, nome, content)
        saved.append(dest.name)

    if not saved:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    return UploadResponseSchema(
        session_id=session_id, files_saved=saved, warnings=warnings, adicionado_ao_quadro=adicionado
    )


@router.post("/{session_id}/ingest", response_model=IngestaoResponseSchema)
def ingest_session(
    session_id: str,
    background_tasks: BackgroundTasks,
) -> IngestaoResponseSchema:
    try:
        session_dir = store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    uploads = store.uploads_dir(session_id)
    meta = store.get_meta(session_id)
    ja_lidos = set(meta.get("pdfs_ingeridos", []))
    pdfs = sorted(
        (p for p in uploads.iterdir() if p.suffix.lower() in UPLOAD_FIELDS["pdf"]),
        key=lambda p: p.stat().st_mtime,
    )
    novos_pdfs = [p for p in pdfs if p.name not in ja_lidos]
    xlsb = _find_file(uploads, UPLOAD_FIELDS["xlsb"])
    msg = _find_file(uploads, UPLOAD_FIELDS["msg"])
    atual = store.load_ingestao(session_id)

    if not atual or not novos_pdfs:
        # Primeira lista do dia (ou reprocessar a sessão): comportamento original.
        motor = MotorIngestao(str(session_dir))
        motor.executar(caminho_pdf=str(pdfs[0]) if pdfs else "", caminho_xlsb=xlsb, caminho_msg=msg)
        payload = motor.para_dict()
        store.save_ingestao(session_id, payload)
        store.update_meta(session_id, pdfs_ingeridos=[p.name for p in pdfs[:1]])
        avisos, erros, linhas_novas = motor.avisos, motor.erros, len(payload["consolidados"])
        # Outras listas que vieram juntas no mesmo upload entram em seguida.
        restantes = pdfs[1:]
    else:
        payload, avisos, erros, linhas_novas, restantes = atual, [], [], 0, novos_pdfs

    for pdf_extra in restantes:
        novas, av, er = _adicionar_lista_ao_quadro(session_id, session_dir, pdf_extra, xlsb, msg)
        payload = store.load_ingestao(session_id)
        avisos += av
        erros += er
        linhas_novas += novas

    if tem_pendentes_ia(payload):
        background_tasks.add_task(processar_fila_llm, session_id)

    _, consolidados_ativos, _ = _get_active_consolidados(session_id)
    return IngestaoResponseSchema(
        session_id=session_id,
        linhas_novas=linhas_novas,
        resumo=ResumoIngestaoSchema(**payload["resumo"]),
        consolidados=[_consolidado_com_pendencias(c) for c in consolidados_ativos],
        avisos=avisos,
        erros=erros,
    )


def _chave_linha(c: dict[str, Any]) -> str:
    return (
        chave_linha_solicitacao(c.get("numero_solicitacao", ""), c.get("seq_solicitacao", ""), c.get("id_item", ""))
        or c.get("id_item")
        or c.get("numero_pedido", "")
    )


def _adicionar_lista_ao_quadro(
    session_id: str, session_dir: Path, pdf: Path, xlsb: str, msg: str
) -> tuple[int, list[str], list[str]]:
    """
    Lê mais uma lista do dia e junta ao quadro: linhas já existentes (o que o
    operador editou) ficam como estão; só as novas entram.
    """
    motor = MotorIngestao(str(session_dir))
    motor.executar(caminho_pdf=str(pdf), caminho_xlsb=xlsb, caminho_msg=msg)
    novo = motor.para_dict()
    atual = store.load_ingestao(session_id) or novo
    existentes = {_chave_linha(c) for c in atual.get("consolidados", [])}
    novas = [c for c in novo.get("consolidados", []) if _chave_linha(c) not in existentes]

    if atual is not novo:
        atual["consolidados"] = atual.get("consolidados", []) + novas
        atual["pedidos_pdf"] = atual.get("pedidos_pdf", []) + novo.get("pedidos_pdf", [])
        atual.setdefault("resumo", {})["consolidados"] = str(len(atual["consolidados"]))
        if isinstance(atual.get("avisos"), list):
            atual["avisos"] += novo.get("avisos", []) if isinstance(novo.get("avisos"), list) else []
    sol = novas[0].get("numero_solicitacao", "") if novas else ""
    aviso = f"Lista {pdf.name}" + (f" (solicitação N°{sol})" if sol else "") + f": {len(novas)} linha(s) nova(s) no quadro."
    store.save_ingestao(session_id, atual)
    meta = store.get_meta(session_id)
    store.update_meta(session_id, pdfs_ingeridos=sorted(set(meta.get("pdfs_ingeridos", [])) | {pdf.name}))

    if novas and store.is_validated(session_id):
        validados = store.load_consolidados_validados(session_id) or {"consolidados": []}
        validados["consolidados"] = validados.get("consolidados", []) + novas
        store.save_consolidados_validados(session_id, validados)
        try:
            arquivar_sessao(session_id, novas, data_entrega=str(meta.get("validated_at", ""))[:10])
        except Exception:  # noqa: BLE001
            pass

    rote = store.load_roteirizacao(session_id)
    if novas and rote:
        quadro = _motor_from_roteirizacao(rote)
        quadro.incluir_linhas_novas([_dict_to_consolidado(c) for c in novas])
        store.save_roteirizacao(session_id, quadro.para_dict())
    return len(novas), [aviso, *motor.avisos], motor.erros


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
        consolidados=[_consolidado_com_pendencias(c) for c in consolidados],
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
        if mesma_linha(raw, pedido_norm):
            found_idx = i
            break

    if found_idx < 0:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_norm} não encontrado.")

    item = ingest["consolidados"][found_idx]
    updates = patch.model_dump(exclude_none=True)

    if updates.get("representante") and updates["representante"] != item.get("representante"):
        # O sistema aprende: próximas solicitações deste cliente já vêm com este nome.
        aprender_representante(item.get("cliente_codigo", ""), updates["representante"])
        updates["representante"] = normalizar_texto(updates["representante"])

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
    body: Optional[ValidacaoConfirmarBodySchema] = None,
) -> ValidacaoConfirmarSchema:
    try:
        ingest = store.load_ingestao(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    if not ingest:
        raise HTTPException(status_code=404, detail="Ingestão não executada.")

    regras_salvas = 0
    memoria_salva = 0
    if body and body.regras_novas:
        regras_validas: dict[str, str] = {}
        for chave, status in body.regras_novas.items():
            if chave.startswith("_") or not status:
                continue
            regras_validas[str(chave)] = str(status)
        if regras_validas:
            regras_salvas = salvar_regras(regras_validas)

    if body and body.memoria_novas:
        memoria_validas: dict[str, str] = {}
        for chave, status in body.memoria_novas.items():
            if chave.startswith("_") or not status or not chave.strip():
                continue
            memoria_validas[str(chave)] = str(status)
        if memoria_validas:
            memoria_salva = salvar_memoria(memoria_validas)

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

    try:
        arquivar_sessao(
            session_id,
            payload.get("consolidados", []),
            data_entrega=store.get_meta(session_id).get("validated_at", "")[:10],
        )
    except Exception:
        pass

    total = len(payload["consolidados"])
    msg = f"Validação confirmada — {total} pedidos prontos para roteirização."
    if regras_salvas:
        msg += f" {regras_salvas} regra(s) salva(s) no aprendizado local."
    if memoria_salva:
        msg += f" {memoria_salva} entrada(s) salva(s) na memória operacional."
    return ValidacaoConfirmarSchema(
        session_id=session_id,
        validated=True,
        total_consolidados=total,
        regras_salvas=regras_salvas,
        message=msg,
    )


@router.post("/{session_id}/roteirizar", response_model=RoteirizacaoSchema)
def roteirizar(session_id: str, recomecar: bool = False) -> RoteirizacaoSchema:
    """
    Primeira vez: monta o quadro do dia. Depois disso vira "Sugerir alocação":
    distribui só o que está sem lugar e NÃO desfaz o que o operador montou.
    `recomecar=true` apaga o quadro e monta tudo de novo.
    """
    try:
        _, consolidados, _ = _get_active_consolidados(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    except HTTPException:
        raise

    existente = store.load_roteirizacao(session_id)
    if existente and not recomecar:
        motor = _motor_from_roteirizacao(existente)
        alocadas, na_fila = motor.sugerir_alocacao(consolidados)
        mensagem = (
            f"Sugestão aplicada: {alocadas} carga(s) alocada(s)"
            + (f", {na_fila} ficaram na fila (sem espaço compatível)" if na_fila else "")
            + ". Nada do que já estava montado foi alterado."
            if alocadas or na_fila
            else "Nada novo para alocar. O quadro continua como você montou."
        )
    else:
        motor = MotorLogistica()
        motor.alocar_frota(consolidados)
        # Equipe: mantém a do dia ao recomeçar; num quadro novo, sugere a última usada.
        motor.equipe_por_veiculo = (existente or {}).get("equipe_por_veiculo") or equipe_inicial()
        mensagem = "Quadro do dia montado." if not existente else "Quadro refeito do zero."
    store.save_roteirizacao(session_id, motor.para_dict())
    return _roteirizacao_from_motor(motor, session_id, mensagem)


@router.post("/{session_id}/veiculos/{veiculo_id}/equipe", response_model=MoverPedidoResponseSchema)
def definir_equipe(session_id: str, veiculo_id: str, body: EquipeVeiculoSchema) -> MoverPedidoResponseSchema:
    """Motorista, ajudante e placa do caminhão no dia (vai para o romaneio)."""

    def aplicar(m: MotorLogistica) -> tuple[bool, str]:
        dados = {k: getattr(body, k).strip().upper() for k in ("motorista", "ajudante", "placa")}
        m.equipe_por_veiculo[veiculo_id] = dados
        lembrar(veiculo_id, dados)
        return True, "Equipe salva."

    return _operar_divisao(session_id, aplicar)


@router.post("/{session_id}/veiculos/{veiculo_id}/fechar", response_model=MoverPedidoResponseSchema)
def fechar_veiculo(session_id: str, veiculo_id: str, body: FecharVeiculoSchema) -> MoverPedidoResponseSchema:
    """Caminhão fechado: a sugestão automática não coloca nem tira nada dele."""
    return _operar_divisao(session_id, lambda m: m.fechar_veiculo(veiculo_id, body.fechado))


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
    data.setdefault("backlog_futuro", [])
    data.setdefault("backlog_local", [])
    data.setdefault("itens_retorno_por_veiculo", {})
    data.setdefault("viagens_retorno_habilitadas", [])
    data.setdefault("metricas_retorno", {})
    motor = _motor_from_roteirizacao(data)
    _enriquecer_teo_motor(motor)
    return _roteirizacao_from_motor(motor, session_id)


def _romaneio_planilha(session_id: str, rote: dict[str, Any], somente_veiculo: str = ""):
    """Romaneio no formato da planilha ROTA DIARIA (templates/romaneio_modelo.xlsx)."""
    from dias_uteis import parse_data_br

    _, consolidados, _ = _get_active_consolidados(session_id)
    linhas = [_consolidado_com_pendencias(c).model_dump() for c in consolidados]
    referencia = next((c.data_referencia for c in consolidados if c.data_referencia), "")
    dia = parse_data_br(referencia)
    conteudo = gerar_romaneio_planilha(rote, linhas, frota_cadastrada(), dia, somente_veiculo=somente_veiculo)
    return conteudo, dia


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
        conteudo, dia = _romaneio_planilha(session_id, data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao gerar romaneio: {exc}") from exc

    filename = f"ROTA DIARIA {dia.strftime('%d_%m_%Y')}.xlsx" if dia else nome_arquivo_romaneio(session_id)
    return StreamingResponse(
        BytesIO(conteudo),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/caminhao/{caminhao_id}/exportar")
def exportar_romaneio_caminhao(session_id: str, caminhao_id: str) -> StreamingResponse:
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    try:
        conteudo, dia = _romaneio_planilha(session_id, data, somente_veiculo=caminhao_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao gerar romaneio: {exc}") from exc

    filename = nome_arquivo_romaneio_caminhao(caminhao_id)
    return StreamingResponse(
        BytesIO(conteudo),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{session_id}/segunda-viagem/{veiculo_id}", response_model=RoteirizacaoSchema)
def habilitar_segunda_viagem(session_id: str, veiculo_id: str) -> RoteirizacaoSchema:
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    motor = _motor_from_roteirizacao(data)
    ok, err = motor.habilitar_segunda_viagem(veiculo_id)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    payload = motor.para_dict()
    store.save_roteirizacao(session_id, payload)
    return _roteirizacao_from_motor(motor, session_id)


@router.post("/{session_id}/mover", response_model=MoverPedidoResponseSchema)
def mover_pedido(session_id: str, body: MoverPedidoSchema) -> MoverPedidoResponseSchema:
    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    motor = _motor_from_roteirizacao(data)

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


@router.post("/{session_id}/dividir", response_model=MoverPedidoResponseSchema)
def dividir_carga(session_id: str, body: DividirCargaSchema) -> MoverPedidoResponseSchema:
    """Divide uma carga por peso; a nova parte fica na mesma coluna."""
    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    motor = _motor_from_roteirizacao(data)
    ok, mensagem = motor.dividir_carga(body.id_carga, body.peso_kg)
    if not ok:
        raise HTTPException(status_code=400, detail=mensagem)

    store.save_roteirizacao(session_id, motor.para_dict())
    return MoverPedidoResponseSchema(
        ok=True,
        warning=mensagem,
        roteirizacao=_roteirizacao_from_motor(motor, session_id),
    )


@router.post(
    "/{session_id}/consulta-representante", response_model=ConsultaRepresentanteResponseSchema
)
def registrar_consulta_representante(
    session_id: str, body: ConsultaRepresentanteBodySchema
) -> ConsultaRepresentanteResponseSchema:
    """
    Registra a resposta do representante para uma ou mais linhas.

    LIBERADO: a linha sai do "Consultar representante" e entra na rota de hoje
    (se a roteirização já foi feita, vai direto para um caminhão compatível).
    NAO_LIBERADO: continua parada até a Dt. Produção. PENDENTE: desfaz a resposta.
    """
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    _, consolidados, _ = _get_active_consolidados(session_id)
    agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    quem = body.autorizado_por.strip()
    rotulo = {"LIBERADO": "Liberado", "NAO_LIBERADO": "Não liberado", "PENDENTE": "Pendente"}[body.resultado]

    atualizados = 0
    liberados: list[str] = []
    tocados: list[str] = []
    for id_linha in body.ids:
        ref = next((c for c in consolidados if mesma_linha(c, id_linha)), None)
        if not ref:
            continue
        linha_audit = f"CONSULTA REPRESENTANTE {agora}: {rotulo}"
        if quem:
            linha_audit += f" por {quem}"
        if body.obs.strip():
            linha_audit += f" — {body.obs.strip()}"
        patch: dict[str, Any] = {
            "consulta_representante": body.resultado,
            "consulta_em": agora if body.resultado != "PENDENTE" else "",
            "consulta_obs": body.obs.strip(),
            "auditoria": (ref.auditoria + " | " + linha_audit).strip(" |"),
        }
        if body.resultado == "LIBERADO":
            patch.update(
                representante_autorizou=quem or ref.representante,
                motivo_adiantamento=f"Liberado pelo representante {quem or ref.representante}",
            )
            liberados.append(ref.id_item or id_linha)
        if body.resultado == "PENDENTE":
            patch["consulta_representante"] = ""
        if _patch_consolidado_session(session_id, ref.id_item or id_linha, patch):
            atualizados += 1
            tocados.append(ref.id_item or id_linha)

    alocados = _alocar_resolvidos(session_id, tocados)
    rote_data = store.load_roteirizacao(session_id)
    msg = f"{atualizados} linha(s) marcada(s) como {rotulo.lower()}."
    if alocados:
        msg += " " + _resumo_sincronizacao(alocados)
    elif liberados and not rote_data:
        msg += " Elas entram na rota na próxima roteirização."
    elif liberados:
        msg += " Algumas ainda têm outra pendência (comercial ou peso) e seguem paradas."
    return ConsultaRepresentanteResponseSchema(
        ok=atualizados > 0, atualizados=atualizados, message=msg, alocados=alocados
    )


@router.post("/{session_id}/liberacao-comercial", response_model=ConsultaRepresentanteResponseSchema)
def registrar_liberacao_comercial(
    session_id: str, body: LiberacaoComercialBodySchema
) -> ConsultaRepresentanteResponseSchema:
    """
    Pagamento antecipado: a linha fica parada no representante até o comercial
    liberar por e-mail. LIBERADO registra quem liberou; AGUARDANDO desfaz.
    """
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    _, consolidados, _ = _get_active_consolidados(session_id)
    agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    quem, obs = body.liberado_por.strip(), body.obs.strip()
    atualizados, liberados, tocados = 0, [], []
    for id_linha in body.ids:
        ref = next((c for c in consolidados if mesma_linha(c, id_linha)), None)
        if not ref:
            continue
        if body.resultado == "LIBERADO":
            linha = f"COMERCIAL LIBEROU {agora}" + (f" por {quem}" if quem else "") + (f" — {obs}" if obs else "")
            patch = {
                "liberacao_comercial": "LIBERADO",
                "liberacao_comercial_por": quem,
                "liberacao_comercial_em": agora,
                "liberacao_comercial_obs": obs,
            }
            liberados.append(ref.id_item or id_linha)
        else:
            linha = f"LIBERAÇÃO COMERCIAL DESFEITA {agora}"
            patch = {
                "liberacao_comercial": "AGUARDANDO",
                "liberacao_comercial_por": "",
                "liberacao_comercial_em": "",
                "liberacao_comercial_obs": "",
            }
        patch["auditoria"] = (ref.auditoria + " | " + linha).strip(" |")
        if _patch_consolidado_session(session_id, ref.id_item or id_linha, patch):
            atualizados += 1
            tocados.append(ref.id_item or id_linha)
    alocados = _alocar_resolvidos(session_id, tocados)
    rotulo = "liberada(s) pelo comercial" if body.resultado == "LIBERADO" else "voltou(aram) a aguardar o comercial"
    msg = f"{atualizados} linha(s) {rotulo}."
    if alocados:
        msg += " " + _resumo_sincronizacao(alocados)
    return ConsultaRepresentanteResponseSchema(ok=atualizados > 0, atualizados=atualizados, message=msg, alocados=alocados)


@router.post("/{session_id}/informar-peso", response_model=ConsultaRepresentanteResponseSchema)
def informar_peso(session_id: str, body: InformarPesoBodySchema) -> ConsultaRepresentanteResponseSchema:
    """Item que veio com peso zerado: a logística informa o peso real."""
    _, consolidados, _ = _get_active_consolidados(session_id)
    ref = next((c for c in consolidados if mesma_linha(c, body.id)), None)
    if not ref:
        raise HTTPException(status_code=404, detail=f"Linha {body.id} não encontrada.")
    agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    peso = round(body.peso_kg, 1)
    patch = {
        "peso_kg": peso,
        "auditoria": (ref.auditoria + f" | PESO INFORMADO {agora}: {formatar_kg(peso)} kg (veio zerado no PDF)").strip(" |"),
    }
    if not _patch_consolidado_session(session_id, ref.id_item or body.id, patch):
        raise HTTPException(status_code=404, detail="Não foi possível atualizar a linha.")
    alocados = _alocar_resolvidos(session_id, [ref.id_item or body.id])
    msg = f"Peso de {ref.cliente} atualizado para {formatar_kg(peso)} kg."
    if alocados:
        msg += " " + _resumo_sincronizacao(alocados)
    return ConsultaRepresentanteResponseSchema(ok=True, atualizados=1, message=msg, alocados=alocados)


def _operar_divisao(session_id: str, operacao) -> MoverPedidoResponseSchema:
    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")
    motor = _motor_from_roteirizacao(data)
    ok, mensagem = operacao(motor)
    if not ok:
        raise HTTPException(status_code=400, detail=mensagem)
    store.save_roteirizacao(session_id, motor.para_dict())
    return MoverPedidoResponseSchema(
        ok=True, warning=mensagem, roteirizacao=_roteirizacao_from_motor(motor, session_id)
    )


@router.post("/{session_id}/dividir/ajustar", response_model=MoverPedidoResponseSchema)
def ajustar_divisao(session_id: str, body: AjustarDivisaoSchema) -> MoverPedidoResponseSchema:
    """Ajuste fino: esta parte fica com peso_kg; a diferença vai para a outra parte."""
    return _operar_divisao(
        session_id,
        lambda m: m.ajustar_divisao(body.id_carga, body.peso_kg, body.id_carga_contrapartida),
    )


@router.post("/{session_id}/dividir/juntar", response_model=MoverPedidoResponseSchema)
def juntar_partes(session_id: str, body: CargaRefSchema) -> MoverPedidoResponseSchema:
    """Desfaz a divisão: todas as partes voltam para este card."""
    return _operar_divisao(session_id, lambda m: m.juntar_partes(body.id_carga))


@router.post("/{session_id}/dividir/confirmar", response_model=MoverPedidoResponseSchema)
def confirmar_divisao(session_id: str, body: CargaRefSchema) -> MoverPedidoResponseSchema:
    """Operador conferiu a divisão automática."""
    return _operar_divisao(session_id, lambda m: m.confirmar_divisao(body.id_carga))


@router.post("/{session_id}/antecipar", response_model=AnteciparPedidoResponseSchema)
def antecipar_pedido(
    session_id: str,
    body: AnteciparPedidoBodySchema,
) -> AnteciparPedidoResponseSchema:
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    rote_data = store.load_roteirizacao(session_id)
    if not rote_data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    motivo = (body.motivo_adiantamento or "").strip()
    if not motivo:
        raise HTTPException(status_code=400, detail="Informe o motivo do adiantamento.")

    rep = (body.representante_autorizou or "").strip()
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    audit_linha = f"ANTECIPADO em {agora}: {motivo}"
    if rep:
        audit_linha += f" | Autorizado por: {rep}"

    _, consolidados, _ = _get_active_consolidados(session_id)
    pedido_ref = next(
        (c for c in consolidados if mesma_linha(c, body.numero_pedido)),
        None,
    )
    if not pedido_ref:
        raise HTTPException(status_code=404, detail=f"Pedido {body.numero_pedido} não encontrado.")

    auditoria = (pedido_ref.auditoria + " | " + audit_linha).strip(" |")
    ok_patch = _patch_consolidado_session(
        session_id,
        body.numero_pedido,
        {
            "data_prevista_recebimento": "",
            "motivo_adiantamento": motivo,
            "representante_autorizou": rep,
            "status": config.COD_LIBERADO,
            "auditoria": auditoria,
        },
    )
    if not ok_patch:
        raise HTTPException(status_code=404, detail="Não foi possível atualizar o consolidado.")

    motor = _motor_from_roteirizacao(rote_data)

    ok, err, destino = motor.antecipar_para_hoje(body.numero_pedido)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    payload = motor.para_dict()
    store.save_roteirizacao(session_id, payload)

    destino_msg = {
        "BACKLOG": "fila de alocação de hoje",
    }.get(destino, destino)
    if destino not in ("BACKLOG",):
        for r in motor.rotas:
            if r.veiculo_id == destino:
                destino_msg = r.veiculo_nome
                break

    return AnteciparPedidoResponseSchema(
        ok=True,
        session_id=session_id,
        numero_pedido=body.numero_pedido,
        destino=destino,
        message=f"Pedido antecipado e alocado em {destino_msg}.",
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

    campos = ItemRota.__dataclass_fields__
    return ItemRota(**{k: data.get(k, campos[k].default) for k in campos})
