"""Regras do quadro do dia usadas pelos endpoints (sem rotas HTTP aqui)."""

from __future__ import annotations

import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import (  # noqa: E402
    MoverPedidoResponseSchema,
    PedidoConsolidadoSchema,
    RoteirizacaoSchema,
)
from api.session_store import store  # noqa: E402
from models import PedidoConsolidado  # noqa: E402
from motor_ingestao import MotorIngestao  # noqa: E402
from motor_logistica import MotorLogistica  # noqa: E402
import config  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from normalizador import mesma_linha, normalizar_texto, resolver_rota_logistica, normalizar_codigo_cliente  # noqa: E402
from pendencias import (  # noqa: E402
    CONSULTA_REPRESENTANTE,
    motivo_parado,
    pendencias as calc_pendencias,
)
from equipe import nomes_conhecidos, frota_cadastrada  # noqa: E402
from romaneio_planilha import gerar_romaneio_planilha  # noqa: E402
import geocodificacao  # noqa: E402
from param_manager import carregar_parametros  # noqa: E402
from historico_manager import arquivar_sessao, chave_linha_solicitacao  # noqa: E402
from conferencia_frete import evidencia as evidencia_frete  # noqa: E402
from destino_entrega import destino_remessa, empresas_remessa, rotulo as rotulo_entrega  # noqa: E402
from extrator_clientes import obter_lookup_clientes  # noqa: E402
from transportadoras import (  # noqa: E402
    campos_da_linha as campos_transportadora,
    carregar as carregar_transportadoras,
    endereco_transportadora,
)
from frases import analisar as analisar_frases  # noqa: E402
from virada_do_dia import juntar_ao_quadro_novo, pendentes_do_quadro  # noqa: E402


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
        agenda = motor.agenda.get(vid)
        if agenda and agenda.get("assinatura") != motor.assinatura_carga(vid):
            agenda = None  # carga mudou depois: horários previstos não valem mais
        if sem_local and session_id and not os.environ.get("LOGISTICA_SEM_GEO_AUTO"):
            try:
                _iniciar_geocodificacao(session_id, automatico=True)
            except HTTPException:
                pass
        painel[vid] = {
            "localizando": bool(sem_local) and bool(_geocodificando.get(session_id, {}).get("rodando")),
            # por que ainda não localizou (sem internet / serviço de mapas bloqueado)
            "erro_localizacao": (_geocodificando.get(session_id, {}).get("erro") or "") if sem_local else "",
            "agenda": agenda,
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
    motor.agenda = dict(data.get("agenda", {}))
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


def _trocar_transportadora_na_linha(item: dict[str, Any], codigo: str, params: dict[str, Any]) -> None:
    """Conferência: o representante disse qual é a transportadora (código da base)."""

    cod = normalizar_codigo_cliente(codigo or "")
    base = carregar_transportadoras()
    if not cod or cod not in base:
        raise HTTPException(
            status_code=400,
            detail=f"A transportadora {(cod or codigo).lstrip('0') or codigo} não está na base de transportadoras.",
        )
    info = endereco_transportadora(cod, "", base)
    if item.get("status") == config.COD_TERCEIRO_HUB and "_antes_hub" not in item:
        item["_antes_hub"] = {k: item[k] for k in _CAMPOS_HUB if k in item}
    item["transportadora"] = info.get("nome", "")
    item["transportadora_codigo"] = cod
    if item.get("status") == config.COD_TERCEIRO_HUB:
        item.update(campos_transportadora(info, params))
        if not info.get("horario"):
            item["obs_recebimento"] = ""
    agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    item["auditoria"] = (
        item.get("auditoria", "") + f" | TRANSPORTADORA DEFINIDA {agora}: {info.get('nome', '')} (cód. {cod.lstrip('0')})"
    ).strip(" |")


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


# ------------------------------------------------------------- mapa e sequência
_geocodificando: dict[str, dict[str, Any]] = {}


def _linhas_do_quadro(session_id: str) -> list[dict[str, Any]]:
    _, consolidados, _ = _get_active_consolidados(session_id)
    return [asdict(c) for c in consolidados]


def _iniciar_geocodificacao(session_id: str, automatico: bool = False) -> dict[str, Any]:
    """
    Localiza no mapa (em segundo plano) os destinos deste quadro que ainda não
    têm coordenada. Automático (quadro aberto): no máximo a cada 10 min, para
    não insistir quando o serviço de mapas está fora do ar.
    """
    atual = _geocodificando.get(session_id, {})
    if atual.get("rodando"):
        return atual
    if automatico and time.time() - atual.get("iniciado_em", 0) < 600:
        return atual
    linhas = _linhas_do_quadro(session_id)
    base, cache = geocodificacao.enderecos_base(), geocodificacao.carregar_cache()
    faltam = len({geocodificacao.chave_da_linha(l, base) for l in linhas} - set(cache) - {""})
    estado = {"rodando": faltam > 0, "total": faltam, "feitos": 0, "nao_achados": [], "erro": "",
              "iniciado_em": time.time()}
    _geocodificando[session_id] = estado
    if not faltam:
        return estado

    def tarefa() -> None:
        def progresso(p: dict[str, Any]) -> None:
            _geocodificando[session_id].update(p)

        try:
            resultado = geocodificacao.geocodificar_linhas(linhas, progresso=progresso)
            geocodificacao.garantir_deposito()
            _geocodificando[session_id].update(resultado, rodando=False)
        except Exception as exc:  # noqa: BLE001
            _geocodificando[session_id].update(rodando=False, erro=str(exc))

    threading.Thread(target=tarefa, daemon=True).start()
    return estado


def _contexto_agenda(session_id: str) -> dict[str, Any]:
    """Tudo o que a agenda de um caminhão precisa (carregado uma vez por chamada)."""
    import horarios_clientes

    params = carregar_parametros()
    inicio = str(params.get("inicio_expediente", "07:00"))
    try:
        h, _, mnt = inicio.partition(":")
        inicio_min = int(h) * 60 + int(mnt or 0)
    except ValueError:
        inicio_min = 7 * 60
    cache, base = _geo_contexto()
    try:
        consolidados = {l.get("id_item"): l for l in _linhas_do_quadro(session_id)}
    except HTTPException:
        consolidados = {}
    return {
        "params": params,
        "deposito": geocodificacao.deposito(params),
        "inicio_min": inicio_min,
        "velocidade": float(params.get("velocidade_media_kmh", 50) or 50),
        "velocidade_estrada": float(params.get("velocidade_estrada_kmh", 75) or 75),
        "fator_afastar": 2.0 if params.get("entrega_de_fora_para_dentro", True) else 0.0,
        "descarga": int(params.get("tempo_descarga_minutos", 20)),
        "padrao": str(params.get("recebimento_padrao") or horarios_clientes.PADRAO),
        "memoria": horarios_clientes.carregar(),
        "cache": cache,
        "base": base,
        "consolidados": consolidados,
    }


def _paradas_do_caminhao(m: MotorLogistica, vid: str, ctx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from horarios_clientes import janela_da_parada

    paradas: dict[str, dict[str, Any]] = {}
    for it in m.itens_por_veiculo.get(vid, []):
        chave = f"{it.cliente_codigo}|{it.cidade_destino}".upper()
        if chave in paradas:
            continue
        linha = {**ctx["consolidados"].get(it.id_item, {}), **{k: v for k, v in asdict(it).items() if v}}
        ponto = geocodificacao.coordenada_da_linha(linha, ctx["cache"], ctx["base"])
        janela, origem = janela_da_parada(linha, ctx["memoria"], ctx["padrao"])
        paradas[chave] = {
            "id": chave,
            "lat": ponto["lat"] if ponto else None,
            "lon": ponto["lon"] if ponto else None,
            "janela": janela,
            "origem_janela": origem,
        }
    return paradas


def _gravar_agenda(m: MotorLogistica, vid: str, agenda: dict[str, Any], paradas: dict[str, dict[str, Any]]) -> None:
    from otimizacao import hhmm

    m.agenda[vid] = {
        "assinatura": m.assinatura_carga(vid),
        "saida": hhmm(agenda["saida"]),
        "volta": hhmm(agenda["volta"]),
        "paradas": {
            a["id"]: {
                "chegada": hhmm(a["chegada"]) if a["chegada"] is not None else "",
                "espera_min": a["espera"],
                "atraso_min": a["atraso"],
                "janela": f"{hhmm(a['janela'][0])}–{hhmm(a['janela'][1])}" if a.get("janela") else "",
                "origem_janela": paradas.get(a["id"], {}).get("origem_janela", ""),
            }
            for a in agenda["paradas"]
        },
    }


def _reagendar(m: MotorLogistica, vid: str, ctx: dict[str, Any]) -> None:
    """Recalcula os horários previstos mantendo a ordem atual."""
    from otimizacao import simular

    paradas = _paradas_do_caminhao(m, vid, ctx)
    if not paradas:
        m.agenda.pop(vid, None)
        return
    agenda = simular(
        list(paradas.values()), ctx["deposito"], ctx["inicio_min"], ctx["velocidade"], ctx["descarga"],
        ctx["velocidade_estrada"],
    )
    _gravar_agenda(m, vid, agenda, paradas)


def _tirar_transportadora_a_definir(motor: MotorLogistica, session_id: str) -> list[str]:
    """
    "Transportadora a definir" não sobe no caminhão sem o representante liberar.
    Linha que já estava num caminhão (quadro montado antes da regra, ou a
    transportadora voltou a ficar a definir) volta para o quadro do representante.
    """
    from pendencias import transportadora_a_definir

    try:
        _, consolidados, _ = _get_active_consolidados(session_id)
    except HTTPException:
        return []
    limite = _limite_consulta()
    no_caminhao = {
        (it.id_item or it.numero_pedido)
        for itens in motor.itens_por_veiculo.values()
        for it in itens
    }
    tirados: list[str] = []
    for c in consolidados:
        id_linha = c.id_item or c.numero_pedido
        if id_linha not in no_caminhao or not transportadora_a_definir(c):
            continue
        if CONSULTA_REPRESENTANTE not in calc_pendencias(c, limite):
            continue  # representante já liberou
        motivo = motivo_parado(c, limite)
        if motor.tirar_do_caminhao_por_pendencia(id_linha, motivo):
            for entry in motor.backlog_futuro:
                if mesma_linha(entry, id_linha):
                    entry.update(
                        pendencias=",".join(calc_pendencias(c, limite)),
                        representante=c.representante,
                        transportadora=c.transportadora,
                        transportadora_codigo=c.transportadora_codigo,
                        consulta_representante=c.consulta_representante or "",
                    )
            tirados.append(id_linha)
    return tirados


def _romaneio_planilha(session_id: str, rote: dict[str, Any], somente_veiculo: str = ""):
    """Romaneio no formato da planilha ROTA DIARIA (templates/romaneio_modelo.xlsx)."""
    from dias_uteis import parse_data_br

    _, consolidados, _ = _get_active_consolidados(session_id)
    linhas = [_consolidado_com_pendencias(c).model_dump() for c in consolidados]
    referencia = next((c.data_referencia for c in consolidados if c.data_referencia), "")
    dia = parse_data_br(referencia)
    conteudo = gerar_romaneio_planilha(rote, linhas, frota_cadastrada(), dia, somente_veiculo=somente_veiculo)
    return conteudo, dia


def _definir_transportadora(session_id: str, ids: list[str], codigo: str) -> list[str]:
    """
    "Transportadora a definir": o representante informou a transportadora.
    Troca nas linhas (conferência e quadro) e o destino passa a ser o endereço dela.
    Só mexe nas linhas que estão como "a definir". Retorna os ids alterados.
    """
    from pendencias import transportadora_a_definir

    cod = normalizar_codigo_cliente(codigo or "")
    if not cod:
        return []
    base = carregar_transportadoras()
    if cod not in base:
        raise HTTPException(
            status_code=400,
            detail=f"A transportadora {cod.lstrip('0') or cod} não está na base de transportadoras.",
        )
    info = endereco_transportadora(cod, "", base)
    campos = campos_transportadora(info, carregar_parametros())
    campos.update(transportadora=info.get("nome", ""), transportadora_codigo=cod)
    if not info.get("horario"):
        campos["obs_recebimento"] = ""
    _, consolidados, _ = _get_active_consolidados(session_id)
    alterados: list[str] = []
    for id_bruto in ids:
        id_linha = id_bruto.split("@")[0]
        ref = next((c for c in consolidados if mesma_linha(c, id_linha)), None)
        if ref is None or not transportadora_a_definir(ref) or ref.id_item in alterados:
            continue
        agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
        patch = dict(campos)
        patch["auditoria"] = (
            ref.auditoria + f" | TRANSPORTADORA DEFINIDA {agora}: {info.get('nome', '')} (cód. {cod.lstrip('0')})"
        ).strip(" |")
        if _patch_consolidado_session(session_id, ref.id_item or id_linha, patch):
            alterados.append(ref.id_item or id_linha)
    if not alterados:
        return []
    # O quadro guarda uma cópia de cada linha: atualiza também (sem passo no "Desfazer")
    data = store.load_roteirizacao(session_id)
    if data:
        listas = [data.get("backlog", []), data.get("backlog_futuro", []), data.get("backlog_local", [])]
        listas += list((data.get("itens_por_veiculo") or {}).values())
        listas += list((data.get("itens_retorno_por_veiculo") or {}).values())
        for lista in listas:
            for entry in lista:
                if not isinstance(entry, dict):
                    continue
                if any(mesma_linha(entry, a) for a in alterados):
                    for k, v in campos.items():
                        if k in entry:
                            entry[k] = "" if v is None and isinstance(entry[k], str) else v
        store.save_roteirizacao(session_id, data, desfazivel=False)
    return alterados


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
