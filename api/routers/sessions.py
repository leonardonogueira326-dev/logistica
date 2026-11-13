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
    ConferirFreteBodySchema,
    EnsinarFraseBodySchema,
    FecharVeiculoSchema,
    NaoSaiuSchema,
    MoverPedidoSchema,
    MoverLoteSchema,
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
from pendencias import (  # noqa: E402
    CONSULTA_REPRESENTANTE,
    PAGAMENTO_ANTECIPADO,
    PESO_ZERADO,
    motivo_parado,
    pendencias as calc_pendencias,
)
from representantes import aprender_representante  # noqa: E402
from equipe import guardar_nomes, nomes_conhecidos, equipe_inicial, frota_cadastrada, lembrar  # noqa: E402
from romaneio_planilha import gerar_romaneio_planilha  # noqa: E402
import geocodificacao  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from param_manager import carregar_parametros  # noqa: E402
from gerador_romaneio import (  # noqa: E402
    gerar_romaneio_caminhao_xlsx,
    gerar_romaneio_xlsx,
    nome_arquivo_romaneio,
    nome_arquivo_romaneio_caminhao,
)
from historico_manager import arquivar_sessao, chave_linha_solicitacao  # noqa: E402
from conferencia_frete import carregar_memoria as carregar_memoria_frete  # noqa: E402
from conferencia_frete import evidencia as evidencia_frete  # noqa: E402
from conferencia_frete import lembrar as lembrar_conferencia_frete  # noqa: E402
from frases import chave as chave_frase  # noqa: E402
from frases import FRETE as SIG_FRETE  # noqa: E402
from frases import INDUSTRIALIZACAO as SIG_INDUSTRIALIZACAO  # noqa: E402
from destino_entrega import destino_remessa, empresas_remessa, rotulo as rotulo_entrega  # noqa: E402
from extrator_clientes import obter_lookup_clientes  # noqa: E402
from transportadoras import campos_da_linha as campos_transportadora, endereco_transportadora  # noqa: E402
from frases import analisar as analisar_frases  # noqa: E402
from frases import carregar as carregar_frases  # noqa: E402
from frases import ensinar as ensinar_frase  # noqa: E402
from frases import quebrar as quebrar_frases  # noqa: E402
from virada_do_dia import juntar_ao_quadro_novo, pendentes_do_quadro  # noqa: E402

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


def _consolidado_com_pendencias(
    c: PedidoConsolidado,
    limite: int | None = None,
    geo: tuple[dict, dict] | None = None,
    memoria_frete: dict | None = None,
    dic_frases: dict | None = None,
) -> PedidoConsolidadoSchema:
    limite = _limite_consulta() if limite is None else limite
    dados = asdict(c)
    if geo is not None and (dados.get("latitude") is None or dados.get("longitude") is None):
        ponto = geocodificacao.coordenada_da_linha(dados, *geo)
        if ponto:
            dados["latitude"], dados["longitude"] = ponto["lat"], ponto["lon"]
    texto_ev, nivel_ev = evidencia_frete(c, memoria_frete)
    dados.pop("evidencia_frete", None)
    return PedidoConsolidadoSchema(
        **dados,
        pendencias=calc_pendencias(c, limite),
        motivo_parado=motivo_parado(c, limite),
        evidencia_frete=texto_ev,
        evidencia_nivel=nivel_ev,
        frases=analisar_frases(c.observacao_comercial, dic_frases),
    )


def _geo_contexto() -> tuple[dict, dict]:
    """(cache de coordenadas, base de endereços) — carregados uma vez por chamada."""
    return geocodificacao.carregar_cache(), geocodificacao.enderecos_base()


def _nomes_veiculos(motor: MotorLogistica) -> dict[str, str]:
    """Nome para mensagens; desambigua quando dois caminhões têm o mesmo nome."""
    contagem: dict[str, int] = {}
    for r in motor.rotas:
        contagem[r.veiculo_nome] = contagem.get(r.veiculo_nome, 0) + 1
    return {
        r.veiculo_id: (r.veiculo_nome if contagem[r.veiculo_nome] == 1 else f"{r.veiculo_nome} · {_numero_veiculo(motor, r)}")
        for r in motor.rotas
    }


def _numero_veiculo(motor: MotorLogistica, rota: Any) -> str:
    """1, 2… entre os caminhões de mesmo nome (pela ordem do cadastro)."""
    iguais = [r.veiculo_id for r in motor.rotas if r.veiculo_nome == rota.veiculo_nome]
    return str(iguais.index(rota.veiculo_id) + 1)


def _painel_veiculos(motor: MotorLogistica, session_id: str) -> dict[str, dict[str, Any]]:
    """Por caminhão: nome sem ambiguidade, ordem otimizada?, paradas sem localização, sugestão de corredor."""
    nomes = _nomes_veiculos(motor)
    try:
        consolidados = {l.get("id_item"): l for l in _linhas_do_quadro(session_id)}
    except HTTPException:
        consolidados = {}
    cache, base = _geo_contexto()
    painel: dict[str, dict[str, Any]] = {}
    for rota in motor.rotas:
        vid = rota.veiculo_id
        sem_local: list[str] = []
        for grupo in (motor.itens_por_veiculo.get(vid, []), motor.itens_retorno_por_veiculo.get(vid, [])):
            for it in grupo:
                linha = {**consolidados.get(it.id_item, {}), **{k: v for k, v in asdict(it).items() if v}}
                if not geocodificacao.coordenada_da_linha(linha, cache, base):
                    sem_local.append(it.id_carga or it.id_item or it.numero_pedido)
        sug = motor.sugestao_corredor(vid, nomes) if rota.alerta_elastico else {"texto": "", "ids": [], "destino": ""}
        painel[vid] = {
            "nome": nomes.get(vid, rota.veiculo_nome),
            "ordem_otimizada": motor.ordem_otimizada(vid),
            "sem_localizacao": sem_local,
            "sugestao_corredor": sug["texto"],
            "sugestao_ids": sug["ids"],
            "sugestao_destino": sug["destino"],
        }
    return painel


_COLUNAS_NAO_VEICULO = {
    "BACKLOG",
    "COLETAS",
    config.COD_BACKLOG_FUTURO,
    config.COD_BACKLOG_LOCAL,
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
        painel_veiculos=_painel_veiculos(motor, session_id),
        equipe_nomes=nomes_conhecidos(),
        desfazer_disponivel=getattr(store, "qtd_desfazer", lambda _sid: 0)(session_id),
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
    motor.veiculos_nao_sairam = list(data.get("veiculos_nao_sairam", []))
    motor.equipe_por_veiculo = dict(data.get("equipe_por_veiculo", {}))
    motor.sequencia_otimizada = dict(data.get("sequencia_otimizada", {}))
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


# Campos que a remessa para industrialização troca (para poder desfazer)
_CAMPOS_DESTINO = (
    "status", "tipo_frete", "cidade", "cidade_destino", "bairro", "bairro_destino", "cep", "cep_destino",
    "entrega_em", "entrega_cliente_codigo", "rota_logistica", "industrializacao", "latitude", "longitude",
    "enriquecido_mestre",
)
PREFIXO_REMESSA = "Remessa para industrialização"


def _aplicar_remessa_na_linha(session_id: str, item: dict[str, Any], empresa: str, origem: str) -> None:
    """A logística leva o material até a empresa que industrializa (peso zerado = ida)."""
    empresa = normalizar_texto(empresa)
    if empresa not in empresas_remessa():
        raise HTTPException(status_code=400, detail=f"Empresa de industrialização desconhecida: {empresa}")
    if "_antes_remessa" not in item:
        item["_antes_remessa"] = {k: item[k] for k in _CAMPOS_DESTINO if k in item}
    destino = destino_remessa(empresa, obter_lookup_clientes(str(store.session_path(session_id))))
    item["status"] = config.COD_LIBERADO
    item["tipo_frete"] = "ENTREGA_DIRETA"
    item["industrializacao"] = f"{PREFIXO_REMESSA}: {empresa}"
    if destino.get("cidade"):
        item["entrega_em"] = rotulo_entrega(destino)
        item["entrega_cliente_codigo"] = destino.get("codigo", "")
        item["cidade"] = item["cidade_destino"] = normalizar_texto(destino["cidade"])
        item["bairro"] = item["bairro_destino"] = normalizar_texto(destino.get("bairro", ""))
        item["cep"] = item["cep_destino"] = destino.get("cep", "")
        item["latitude"] = item["longitude"] = None
        item["rota_logistica"] = resolver_rota_logistica(item["cidade_destino"], carregar_parametros())
        item["enriquecido_mestre"] = "SIM"  # endereço da empresa veio da base de clientes
    else:
        item["entrega_em"] = f"{empresa} — endereço não encontrado na base, confira"
    item["auditoria"] = (item.get("auditoria", "") + f" | REMESSA P/ INDUSTRIALIZAÇÃO ({empresa}) — {origem}").strip(" |")


def _desfazer_remessa_na_linha(item: dict[str, Any]) -> None:
    antes = item.pop("_antes_remessa", None)
    if antes is not None:
        for k in _CAMPOS_DESTINO:
            if k in antes:
                item[k] = antes[k]
            else:
                item.pop(k, None)
    elif str(item.get("industrializacao", "")).startswith(PREFIXO_REMESSA):
        item["industrializacao"] = ""
        item["entrega_em"] = ""
    item["auditoria"] = (item.get("auditoria", "") + " | REMESSA P/ INDUSTRIALIZAÇÃO DESFEITA").strip(" |")


_CAMPOS_HUB = (
    "entrega_em", "entrega_cliente_codigo", "cidade_destino", "cidade", "bairro_destino", "bairro", "cep_destino",
    "estado_destino", "enriquecido_mestre", "latitude", "longitude", "obs_recebimento", "rota_logistica",
)


def _levar_na_transportadora(item: dict[str, Any], params: dict[str, Any]) -> None:
    """Frete trocado para 'Levar na transportadora': o destino passa a ser a transportadora."""
    if "_antes_hub" not in item:
        item["_antes_hub"] = {k: item[k] for k in _CAMPOS_HUB if k in item}
    info = endereco_transportadora(str(item.get("transportadora_codigo") or ""), str(item.get("transportadora") or ""))
    item.update(campos_transportadora(info, params))
    if not info.get("horario"):
        item["obs_recebimento"] = ""


def _desfazer_transportadora(item: dict[str, Any]) -> None:
    antes = item.pop("_antes_hub", None)
    if antes is None:
        return
    for k in _CAMPOS_HUB:
        if k in antes:
            item[k] = antes[k]
        else:
            item.pop(k, None)


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


def _ids_no_quadro(rote: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    grupos = [*rote.get("itens_por_veiculo", {}).values(), *rote.get("itens_retorno_por_veiculo", {}).values()]
    grupos += [rote.get(k, []) for k in ("backlog", "backlog_futuro", "backlog_local", "coletas")]
    for itens in grupos:
        for it in itens:
            ids.add(str(it.get("id_item") or it.get("numero_pedido") or "").split("@")[0])
    return ids


def _quadro_anterior(session_id: str, data_ref: str) -> str:
    """Quadro do dia mais recente ANTES desta data (o "ontem" deste quadro)."""
    candidatos = [
        q for q in store.listar_quadros(500)
        if q["session_id"] != session_id and q.get("data_referencia") and q["data_referencia"] < data_ref
    ]
    if not candidatos:
        return ""
    candidatos.sort(key=lambda q: (q["data_referencia"], q.get("atualizado_em", "")), reverse=True)
    return candidatos[0]["session_id"]


def _trazer_do_dia_anterior(session_id: str, payload: dict[str, Any]) -> list[str]:
    """Quadro novo: o que não saiu no dia anterior entra aqui com 'pendente desde'."""
    consolidados = payload.get("consolidados", [])
    data_ref = next((c.get("data_referencia") for c in consolidados if c.get("data_referencia")), "")
    anterior = _quadro_anterior(session_id, data_ref) if data_ref else ""
    if not anterior:
        return []
    try:
        dados = (
            store.load_consolidados_validados(anterior) if store.is_validated(anterior) else None
        ) or store.load_ingestao(anterior) or {}
        pendentes = pendentes_do_quadro(dados.get("consolidados", []), store.load_roteirizacao(anterior))
    except Exception as exc:  # noqa: BLE001 — virada não pode impedir o dia novo
        return [f"Não consegui trazer as pendências do dia anterior: {exc}"]
    if not pendentes:
        return []
    feriados = carregar_parametros().get("feriados_extras", [])
    juntos, trazidas, herdadas = juntar_ao_quadro_novo(consolidados, pendentes, data_ref, feriados)
    payload["consolidados"] = juntos
    payload.setdefault("resumo", {})["consolidados"] = str(len(juntos))
    store.save_ingestao(session_id, payload)
    store.update_meta(session_id, quadro_anterior=anterior)
    partes = []
    if trazidas:
        partes.append(f"{trazidas} linha(s) que não saíram no dia anterior entraram neste quadro")
    if herdadas:
        partes.append(f"{herdadas} linha(s) do PDF novo já estavam pendentes antes")
    return ["Virada do dia: " + "; ".join(partes) + "."]


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

    # Linhas novas esperam a conferência: entram no quadro quando o operador der o ✓.
    if novas:
        aviso += " Confira as linhas novas para elas irem para o Kanban."
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


# ------------------------------------------------------------- mapa e sequência
_geocodificando: dict[str, dict[str, Any]] = {}


def _linhas_do_quadro(session_id: str) -> list[dict[str, Any]]:
    _, consolidados, _ = _get_active_consolidados(session_id)
    return [asdict(c) for c in consolidados]


@router.post("/{session_id}/geocodificar", tags=["mapa"])
def iniciar_geocodificacao(session_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Localiza no mapa os clientes deste quadro que ainda não têm coordenada (em segundo plano)."""
    if _geocodificando.get(session_id, {}).get("rodando"):
        return _geocodificando[session_id]
    linhas = _linhas_do_quadro(session_id)
    base, cache = geocodificacao.enderecos_base(), geocodificacao.carregar_cache()
    faltam = len({geocodificacao.chave_da_linha(l, base) for l in linhas} - set(cache) - {""})
    estado = {"rodando": faltam > 0, "total": faltam, "feitos": 0, "nao_achados": [], "erro": ""}
    _geocodificando[session_id] = estado

    def tarefa() -> None:
        def progresso(p: dict[str, Any]) -> None:
            _geocodificando[session_id].update(p)

        resultado = geocodificacao.geocodificar_linhas(linhas, progresso=progresso)
        geocodificacao.garantir_deposito()
        _geocodificando[session_id].update(resultado, rodando=False)

    if faltam:
        background_tasks.add_task(tarefa)
    return estado


@router.get("/{session_id}/geocodificar", tags=["mapa"])
def status_geocodificacao(session_id: str) -> dict[str, Any]:
    linhas = _linhas_do_quadro(session_id)
    base, cache = geocodificacao.enderecos_base(), geocodificacao.carregar_cache()
    chaves = {geocodificacao.chave_da_linha(l, base) for l in linhas} - {""}
    return {
        **_geocodificando.get(session_id, {"rodando": False}),
        "clientes": len(chaves),
        "localizados": len(chaves & set(cache)),
        "sem_endereco_na_base": not base,
    }


class _PosicaoManual(BaseModel):
    id_item: str
    lat: float
    lon: float


@router.post("/{session_id}/geo/corrigir", tags=["mapa"])
def corrigir_posicao(session_id: str, body: _PosicaoManual) -> dict[str, Any]:
    """Operador arrastou o marcador: vale para este cliente daqui para frente."""
    linha = next((l for l in _linhas_do_quadro(session_id) if mesma_linha(l, body.id_item)), None)
    if not linha:
        raise HTTPException(status_code=404, detail="Linha não encontrada.")
    chave = geocodificacao.chave_da_linha(linha)
    geocodificacao.definir_manual(chave, body.lat, body.lon)
    return {"ok": True, "chave": chave}


class _OtimizarBody(BaseModel):
    veiculo_id: str = ""


@router.post("/{session_id}/otimizar-sequencia", response_model=MoverPedidoResponseSchema, tags=["mapa"])
def otimizar_sequencia(session_id: str, body: _OtimizarBody) -> MoverPedidoResponseSchema:
    """Melhor ordem de entrega (OR-Tools) — um caminhão ou todos os abertos."""
    from dias_uteis import parse_data_br  # noqa: F401
    from otimizacao import janela_recebimento, otimizar

    params = carregar_parametros()
    deposito = geocodificacao.deposito(params)
    inicio = str(params.get("inicio_expediente", "07:00"))
    try:
        h, _, mnt = inicio.partition(":")
        inicio_min = int(h) * 60 + int(mnt or 0)
    except ValueError:
        inicio_min = 7 * 60
    cache, base = _geo_contexto()
    consolidados = {l.get("id_item"): l for l in _linhas_do_quadro(session_id)}

    def aplicar(m: MotorLogistica) -> tuple[bool, str]:
        nomes = _nomes_veiculos(m)
        alvo = [body.veiculo_id] if body.veiculo_id else [v for v in m.itens_por_veiculo if v not in m.veiculos_fechados]
        partes = []
        for vid in alvo:
            itens = m.itens_por_veiculo.get(vid, [])
            if len(itens) < 2:
                continue
            paradas: dict[str, dict[str, Any]] = {}
            for it in itens:
                chave = f"{it.cliente_codigo}|{it.cidade_destino}".upper()
                if chave in paradas:
                    continue
                linha = {**consolidados.get(it.id_item, {}), **{k: v for k, v in asdict(it).items() if v}}
                ponto = geocodificacao.coordenada_da_linha(linha, cache, base)
                paradas[chave] = {
                    "id": chave,
                    "lat": ponto["lat"] if ponto else None,
                    "lon": ponto["lon"] if ponto else None,
                    "janela": janela_recebimento(linha.get("obs_recebimento", "")),
                }
            r = otimizar(list(paradas.values()), deposito, inicio_min,
                         descarga_min=int(params.get("tempo_descarga_minutos", 20)))
            m.aplicar_sequencia(vid, r["ordem"])
            m.recalcular_metricas(vid)
            m.sequencia_otimizada[vid] = m.assinatura_carga(vid)
            sem_local = sum(1 for p in paradas.values() if p["lat"] is None)
            texto = f"{nomes.get(vid, vid)}: {r['km_depois']:.0f} km"
            if sem_local:
                texto += f" ({sem_local} sem localização no fim)"
            partes.append(texto)
        if not partes:
            return True, "Nada para otimizar (caminhões com menos de 2 paradas ou fechados)."
        return True, "Ordem de entrega otimizada — " + "; ".join(partes) + "."

    return _operar_divisao(session_id, aplicar)


@router.post("/{session_id}/veiculos/{veiculo_id}/equipe", response_model=MoverPedidoResponseSchema)
def definir_equipe(session_id: str, veiculo_id: str, body: EquipeVeiculoSchema) -> MoverPedidoResponseSchema:
    """Motorista, ajudante e placa do caminhão no dia (vai para o romaneio)."""

    def aplicar(m: MotorLogistica) -> tuple[bool, str]:
        dados = {k: getattr(body, k).strip().upper() for k in ("motorista", "ajudante", "placa")}
        m.equipe_por_veiculo[veiculo_id] = dados
        lembrar(veiculo_id, dados)
        guardar_nomes(dados)
        return True, "Equipe salva."

    return _operar_divisao(session_id, aplicar)


@router.post("/{session_id}/veiculos/{veiculo_id}/fechar", response_model=MoverPedidoResponseSchema)
def fechar_veiculo(session_id: str, veiculo_id: str, body: FecharVeiculoSchema) -> MoverPedidoResponseSchema:
    """Caminhão fechado: a sugestão automática não coloca nem tira nada dele."""
    return _operar_divisao(session_id, lambda m: m.fechar_veiculo(veiculo_id, body.fechado))


@router.post("/{session_id}/veiculos/{veiculo_id}/nao-saiu", response_model=MoverPedidoResponseSchema)
def marcar_nao_saiu(session_id: str, veiculo_id: str, body: NaoSaiuSchema) -> MoverPedidoResponseSchema:
    """Motorista faltou / caminhão quebrou: a carga passa para o próximo dia."""
    return _operar_divisao(session_id, lambda m: m.marcar_nao_saiu(veiculo_id, body.nao_saiu))


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


@router.post("/{session_id}/desfazer", response_model=MoverPedidoResponseSchema)
def desfazer(session_id: str) -> MoverPedidoResponseSchema:
    """Volta o quadro para antes da última mudança (mover, dividir, sugerir, otimizar…)."""
    anterior = store.desfazer_roteirizacao(session_id)
    if anterior is None:
        raise HTTPException(status_code=400, detail="Nada para desfazer.")
    motor = _motor_from_roteirizacao(anterior)
    _enriquecer_teo_motor(motor)
    return MoverPedidoResponseSchema(
        ok=True, warning="Última mudança desfeita.", roteirizacao=_roteirizacao_from_motor(motor, session_id)
    )


@router.post("/{session_id}/mover-lote", response_model=MoverPedidoResponseSchema)
def mover_lote(session_id: str, body: MoverLoteSchema) -> MoverPedidoResponseSchema:
    """
    Vários cards de uma vez (seleção múltipla / cliente inteiro). Um passo só no
    "Desfazer". O que não pode ir (travado, precisa do representante, sem espaço
    sem forçar) fica onde está e é avisado.
    """
    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")
    motor = _motor_from_roteirizacao(data)
    para_veiculo = body.destino.upper() not in _COLUNAS_NAO_VEICULO
    try:
        _, consolidados, _ = _get_active_consolidados(session_id)
    except HTTPException:
        consolidados = []
    limite = _limite_consulta()
    movidos, ficaram, liberados = 0, [], []
    for id_carga in dict.fromkeys(body.ids):
        ref = next((c for c in consolidados if mesma_linha(c, id_carga.split("@")[0])), None)
        nome = (ref.cliente if ref else id_carga)[:30]
        if para_veiculo and ref is not None:
            abertas = calc_pendencias(ref, limite)
            if PAGAMENTO_ANTECIPADO in abertas or PESO_ZERADO in abertas:
                ficaram.append(f"{nome} (travado)")
                continue
            if CONSULTA_REPRESENTANTE in abertas:
                if not body.liberar_representante:
                    ficaram.append(f"{nome} (falta o representante liberar)")
                    continue
                liberados.append(ref)
        ok, aviso = motor.mover_pedido(id_carga, body.destino, body.motivo, forcar=body.forcar)
        if ok:
            movidos += 1
        else:
            ficaram.append(f"{nome} ({aviso or 'não coube'})")
            if ref in liberados:
                liberados.remove(ref)
    if not movidos:
        raise HTTPException(status_code=400, detail="Nada foi movido: " + "; ".join(ficaram))
    store.save_roteirizacao(session_id, motor.para_dict())
    agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    for ref in liberados:
        quem = body.autorizado_por.strip() or ref.representante
        _patch_consolidado_session(
            session_id,
            ref.id_item or ref.numero_pedido,
            {
                "consulta_representante": "LIBERADO",
                "consulta_em": agora,
                "representante_autorizou": quem,
                "motivo_adiantamento": f"Liberado pelo representante {quem}",
                "auditoria": (ref.auditoria + f" | CONSULTA REPRESENTANTE {agora}: Liberado por {quem} (Kanban)").strip(" |"),
            },
        )
    aviso = f"{movidos} {'card movido' if movidos == 1 else 'cards movidos'}."
    if ficaram:
        aviso += " Ficaram: " + "; ".join(ficaram)
    return MoverPedidoResponseSchema(ok=True, warning=aviso, roteirizacao=_roteirizacao_from_motor(motor, session_id))


@router.post("/{session_id}/mover", response_model=MoverPedidoResponseSchema)
def mover_pedido(session_id: str, body: MoverPedidoSchema) -> MoverPedidoResponseSchema:
    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    motor = _motor_from_roteirizacao(data)

    # Para caminhão: linha travada (comercial / peso zerado) não sobe;
    # consulta ao representante precisa da confirmação do operador.
    ref = None
    if body.destino.upper() not in _COLUNAS_NAO_VEICULO:
        try:
            _, consolidados, _ = _get_active_consolidados(session_id)
        except HTTPException:
            consolidados = []
        id_linha = body.numero_pedido.split("@")[0]
        ref = next((c for c in consolidados if mesma_linha(c, id_linha)), None)
        if ref is not None:
            abertas = calc_pendencias(ref, _limite_consulta())
            travas = [p for p in abertas if p in (PAGAMENTO_ANTECIPADO, PESO_ZERADO)]
            if travas:
                nomes = {PAGAMENTO_ANTECIPADO: "aguardando liberação do comercial", PESO_ZERADO: "peso zerado"}
                raise HTTPException(
                    status_code=400,
                    detail="Linha travada (" + ", ".join(nomes[t] for t in travas)
                    + "). Resolva na página Pendências.",
                )
            if CONSULTA_REPRESENTANTE in abertas and not body.liberar_representante:
                raise HTTPException(
                    status_code=409,
                    detail="Confirme que o representante liberou antes de carregar.",
                )

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

    if ref is not None and body.liberar_representante:
        agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
        quem = body.autorizado_por.strip() or ref.representante
        _patch_consolidado_session(
            session_id,
            ref.id_item or ref.numero_pedido,
            {
                "consulta_representante": "LIBERADO",
                "consulta_em": agora,
                "representante_autorizou": quem,
                "motivo_adiantamento": f"Liberado pelo representante {quem}",
                "auditoria": (ref.auditoria + f" | CONSULTA REPRESENTANTE {agora}: Liberado por {quem} (Kanban)").strip(" |"),
            },
        )
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
