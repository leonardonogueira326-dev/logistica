"""Quadro do dia: upload, leitura da lista, conferência e montagem inicial."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import (  # noqa: E402
    ConsolidadoPatchSchema,
    ConsolidadosListSchema,
    IngestaoResponseSchema,
    ConsultaRepresentanteBodySchema,
    InformarPesoBodySchema,
    LiberacaoComercialBodySchema,
    ConsultaRepresentanteResponseSchema,
    ConferirFreteBodySchema,
    EnsinarFraseBodySchema,
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
from motor_ingestao import MotorIngestao  # noqa: E402
from motor_logistica import MotorLogistica  # noqa: E402
import config  # noqa: E402
from normalizador import formatar_kg, mesma_linha, normalizar_texto, resolver_rota_logistica  # noqa: E402
from representantes import aprender_representante  # noqa: E402
from equipe import equipe_inicial  # noqa: E402
from param_manager import carregar_parametros  # noqa: E402
from historico_manager import arquivar_sessao  # noqa: E402
from conferencia_frete import carregar_memoria as carregar_memoria_frete  # noqa: E402
from conferencia_frete import evidencia as evidencia_frete  # noqa: E402
from conferencia_frete import lembrar as lembrar_conferencia_frete  # noqa: E402
from frases import chave as chave_frase  # noqa: E402
from frases import FRETE as SIG_FRETE  # noqa: E402
from frases import INDUSTRIALIZACAO as SIG_INDUSTRIALIZACAO  # noqa: E402
from frases import carregar as carregar_frases  # noqa: E402
from frases import ensinar as ensinar_frase  # noqa: E402
from frases import quebrar as quebrar_frases  # noqa: E402
from api.servicos.quadro import (  # noqa: E402
    PREFIXO_REMESSA,
    UPLOAD_FIELDS,
    _adicionar_lista_ao_quadro,
    _alocar_resolvidos,
    _aplicar_remessa_na_linha,
    _consolidado_com_pendencias,
    _desfazer_remessa_na_linha,
    _desfazer_transportadora,
    _find_file,
    _geo_contexto,
    _get_active_consolidados,
    _ids_no_quadro,
    _levar_na_transportadora,
    _motor_from_roteirizacao,
    _patch_consolidado_session,
    _resumo_sincronizacao,
    _roteirizacao_from_motor,
    _trazer_do_dia_anterior,
    _trocar_transportadora_na_linha,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", tags=["sessions"])
def listar_quadros(limite: int = 30) -> list[dict[str, Any]]:
    """Quadros do dia salvos no servidor (para abrir de qualquer PC)."""
    return store.listar_quadros(limite)


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
        if not atual:
            avisos = _trazer_do_dia_anterior(session_id, payload) + avisos
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
        consolidados=[
            _consolidado_com_pendencias(c, memoria_frete=mem, dic_frases=dic)
            for mem, dic in [(carregar_memoria_frete(), carregar_frases())]
            for c in consolidados_ativos
        ],
        avisos=avisos,
        erros=erros,
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

    geo = _geo_contexto()
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
        consolidados=[
            _consolidado_com_pendencias(c, geo=geo, memoria_frete=mem, dic_frases=dic)
            for mem, dic in [(carregar_memoria_frete(), carregar_frases())]
            for c in consolidados
        ],
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
    remessa_pedida = updates.pop("remessa_industrializacao", None)
    transp_codigo = updates.pop("transportadora_codigo", None)
    if transp_codigo is not None:
        _trocar_transportadora_na_linha(item, transp_codigo, params)

    if updates.get("representante") and updates["representante"] != item.get("representante"):
        # O sistema aprende: próximas solicitações deste cliente já vêm com este nome.
        aprender_representante(item.get("cliente_codigo", ""), updates["representante"])
        updates["representante"] = normalizar_texto(updates["representante"])

    for key, value in updates.items():
        item[key] = value
        if key in ("bairro", "cidade", "cep"):
            dest_key = f"{key}_destino" if key != "cep" else "cep_destino"
            item[dest_key] = value

    remessa = remessa_pedida
    if remessa is not None:
        if remessa:
            _aplicar_remessa_na_linha(session_id, item, remessa, "escolhida na conferência")
            updates.pop("status", None)
        else:
            _desfazer_remessa_na_linha(item)

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
        era_hub = item.get("tipo_frete") == "ENTREGA_TERCEIRO_HUB"
        if status in tipo_map:
            item["tipo_frete"] = tipo_map[status]
        item["auditoria"] = (
            (item.get("auditoria", "") + " | STATUS AJUSTADO NA VALIDAÇÃO").strip(" |")
        )
        if status == config.COD_TERCEIRO_HUB and not era_hub:
            _levar_na_transportadora(item, params)
        elif era_hub and status != config.COD_TERCEIRO_HUB:
            _desfazer_transportadora(item)

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

    faltam = [c for c in ingest.get("consolidados", []) if c.get("conferida") != "SIM"]
    if faltam and not store.is_validated(session_id):
        raise HTTPException(
            status_code=409,
            detail=f"Faltam {len(faltam)} linha(s) para conferir antes de montar as cargas.",
        )

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
        _, consolidados, validado = _get_active_consolidados(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    except HTTPException:
        raise
    if not validado:
        # Nada vai para os caminhões sem o operador conferir a lista.
        raise HTTPException(
            status_code=409,
            detail="A leitura ainda não foi conferida. Confira a lista em Conferência e clique em 'Montar cargas'.",
        )

    consolidados = [c for c in consolidados if c.conferida == "SIM"]
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


@router.post("/{session_id}/frases/ensinar", response_model=ConsultaRepresentanteResponseSchema)
def ensinar_frase_endpoint(session_id: str, body: EnsinarFraseBodySchema) -> ConsultaRepresentanteResponseSchema:
    """
    O operador ensina o que uma frase nova significa. Vale para sempre (dicionário)
    e, se muda o frete, já corrige as linhas deste quadro que ainda não foram conferidas.
    """
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    try:
        ensinar_frase(body.chave, body.exemplo, body.significado, body.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    corrigidas = 0
    if body.significado == SIG_INDUSTRIALIZACAO:
        ingest = store.load_ingestao(session_id) or {}
        for item in ingest.get("consolidados", []):
            if item.get("conferida") == "SIM" or str(item.get("industrializacao", "")).startswith(PREFIXO_REMESSA):
                continue
            if not any(chave_frase(f) == body.chave for f in quebrar_frases(item.get("observacao_comercial", ""))):
                continue
            try:
                peso = float(item.get("peso_kg") or 0)
            except (TypeError, ValueError):
                peso = 0.0
            if peso > 0:
                item["industrializacao"] = f"Voltou da industrialização ({body.status}) — segue para o cliente"
            else:
                _aplicar_remessa_na_linha(session_id, item, body.status, "frase ensinada")
            corrigidas += 1
        if corrigidas:
            store.save_ingestao(session_id, ingest)
    if body.significado == SIG_FRETE:
        _, consolidados, _ = _get_active_consolidados(session_id)
        for c in consolidados:
            if c.conferida == "SIM" or c.status == body.status:
                continue
            if any(chave_frase(f) == body.chave for f in quebrar_frases(c.observacao_comercial)):
                if _patch_consolidado_session(
                    session_id,
                    c.id_item or c.numero_pedido,
                    {"status": body.status, "auditoria": (c.auditoria + " | FRETE PELA FRASE ENSINADA").strip(" |")},
                ):
                    corrigidas += 1
    msg = "Frase aprendida."
    if corrigidas:
        msg += f" {corrigidas} linha(s) deste quadro foram ajustadas."
    return ConsultaRepresentanteResponseSchema(ok=True, atualizados=corrigidas, message=msg)


@router.post("/{session_id}/conferir", response_model=ConsultaRepresentanteResponseSchema)
@router.post("/{session_id}/conferir-frete", response_model=ConsultaRepresentanteResponseSchema)
def conferir_frete(session_id: str, body: ConferirFreteBodySchema) -> ConsultaRepresentanteResponseSchema:
    """
    Conferência linha a linha: o operador confere a linha (ou desfaz).
    Só linha conferida vai para o Kanban. Se o quadro já está montado, a linha
    conferida agora entra nele (fila / parados), sem mexer no resto.
    """
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    _, consolidados, _ = _get_active_consolidados(session_id)
    agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    memoria = carregar_memoria_frete()
    tocadas, vermelhas, entram = 0, [], []
    for id_linha in body.ids:
        ref = next((c for c in consolidados if mesma_linha(c, id_linha)), None)
        if not ref:
            continue
        if body.conferido and evidencia_frete(ref, memoria)[1] == "VERMELHO":
            vermelhas.append(ref)
        marca = "SIM" if body.conferido else ""
        quando = agora if body.conferido else ""
        patch = {"conferida": marca, "conferida_em": quando, "frete_conferido": marca, "frete_conferido_em": quando}
        if _patch_consolidado_session(session_id, ref.id_item or id_linha, patch):
            tocadas += 1
            if body.conferido and ref.conferida != "SIM":
                ref.conferida = "SIM"
                entram.append(ref)
    aprendidas = lembrar_conferencia_frete(vermelhas) if vermelhas else 0
    rote = store.load_roteirizacao(session_id)
    if entram and rote and store.is_validated(session_id):
        no_quadro = _ids_no_quadro(rote)
        novas = [c for c in entram if (c.id_item or c.numero_pedido) not in no_quadro]
        if novas:
            quadro = _motor_from_roteirizacao(rote)
            quadro.incluir_linhas_novas(novas)
            store.save_roteirizacao(session_id, quadro.para_dict())
    msg = f"{tocadas} linha(s) {'conferida(s)' if body.conferido else 'voltaram para conferir'}."
    if aprendidas:
        msg += f" Aprendi {aprendidas} combinação(ões) cliente + transportadora."
    return ConsultaRepresentanteResponseSchema(ok=True, atualizados=tocadas, message=msg)


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
