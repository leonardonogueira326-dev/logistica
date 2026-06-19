"""
Worker de IA — processa fila PROCESSANDO_IA em background após ingestão.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from api.llm_local import STATUS_ADMINISTRATIVO, classificar_observacao_llm, tipo_frete_da_sugestao  # noqa: E402
from api.session_store import store  # noqa: E402
from extrator_pdf import observacao_apenas_administrativa, tipo_frete_padrao_superfine  # noqa: E402
from models import EventoEmail, PedidoFaturamento, RetencaoFiscal  # noqa: E402
from motor_ingestao import MotorIngestao, calcular_acondicionamento_e_restricoes  # noqa: E402
from quarentena import avaliar_quarentena  # noqa: E402


def _pedido_key(item: dict[str, Any]) -> str:
    return item.get("numero_pedido_norm") or item.get("numero_pedido") or ""


def _indexar_pedidos_pdf(pedidos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapa: dict[str, dict[str, Any]] = {}
    for p in pedidos:
        for chave in (p.get("numero_pedido_norm"), p.get("numero_pedido")):
            if chave:
                mapa[str(chave)] = p
    return mapa


def _dict_to_pedido(data: dict[str, Any]) -> PedidoFaturamento:
    campos = PedidoFaturamento.__dataclass_fields__
    return PedidoFaturamento(**{k: data.get(k, campos[k].default) for k in campos})


def _patch_classificacao_administrativa(
    motor: MotorIngestao,
    item: dict[str, Any],
    pedido: PedidoFaturamento,
    tipo_regex: str,
    mapa_fiscal: dict,
    mapa_email: dict,
    origem: str = "filtro",
) -> dict[str, Any]:
    """Aplica LIBERADO/padrão Superfine sem quarentena por sugestão IA."""
    tipo_final = tipo_frete_padrao_superfine(
        pedido.transportadora,
        pedido.transportadora_codigo,
        tipo_regex,
    )
    pedido.tipo_frete = tipo_final

    status, motivo, auditoria = motor._classificar_pedido(  # noqa: SLF001
        pedido, mapa_fiscal, mapa_email
    )
    revisao, motivo_q, palavra_q = avaliar_quarentena(
        float(item.get("peso_kg") or 0),
        item.get("observacao_comercial", ""),
        pedido.descricao_item,
        pedido.aprendizado_aplicado,
    )

    patch: dict[str, Any] = {
        "status_ia": config.STATUS_IA_CONCLUIDO,
        "sugestao_llm_status": STATUS_ADMINISTRATIVO if origem == "llm" else "",
        "flag_revisao_llm": "NAO",
        "tipo_frete": tipo_final,
        "status": status,
        "motivo_bloqueio": motivo,
        "motivo_alocacao": calcular_acondicionamento_e_restricoes(pedido, motor.params),
        "revisao_obrigatoria": revisao,
        "motivo_quarentena": motivo_q,
        "palavra_chave_quarentena": palavra_q,
        "auditoria": (
            f"{item.get('auditoria', '')} | {origem.upper()}: obs administrativa -> {tipo_final}"
        ).strip(" |"),
    }
    if revisao == config.COD_REVISAO_OBRIGATORIA:
        patch["auditoria"] = (
            f"{patch['auditoria']} | {config.COD_REVISAO_OBRIGATORIA}: {motivo_q}"
        ).strip(" |")
    return patch


def _aplicar_llm_no_item(
    motor: MotorIngestao,
    item: dict[str, Any],
    pedido_pdf: dict[str, Any],
    mapa_fiscal: dict,
    mapa_email: dict,
) -> dict[str, Any]:
    pedido = _dict_to_pedido(pedido_pdf)
    texto_obs = (item.get("observacao_comercial") or pedido.descricao_item or "").strip()
    tipo_regex = item.get("tipo_frete_regex") or item.get("tipo_frete") or pedido.tipo_frete

    if observacao_apenas_administrativa(texto_obs, pedido.descricao_item):
        return _patch_classificacao_administrativa(
            motor, item, pedido, tipo_regex, mapa_fiscal, mapa_email, origem="filtro"
        )

    contexto = (
        f"Transportadora: {pedido.transportadora or 'N/A'} | "
        f"Código transp.: {pedido.transportadora_codigo or 'N/A'} | "
        f"Classificação regex: {tipo_regex}"
    )
    sugestao_llm = classificar_observacao_llm(texto_obs, contexto)

    patch: dict[str, Any] = {"status_ia": config.STATUS_IA_CONCLUIDO}

    if not sugestao_llm:
        patch["status_ia"] = config.STATUS_IA_ERRO
        return patch

    if sugestao_llm == STATUS_ADMINISTRATIVO:
        return _patch_classificacao_administrativa(
            motor, item, pedido, tipo_regex, mapa_fiscal, mapa_email, origem="llm"
        )

    tipo_llm = tipo_frete_da_sugestao(sugestao_llm)
    if not tipo_llm:
        patch["status_ia"] = config.STATUS_IA_ERRO
        return patch

    patch["sugestao_llm_status"] = sugestao_llm

    if tipo_llm != tipo_regex:
        pedido.tipo_frete = tipo_llm
        patch["tipo_frete"] = tipo_llm
        patch["flag_revisao_llm"] = "SIM"

        status, motivo, auditoria = motor._classificar_pedido(  # noqa: SLF001
            pedido, mapa_fiscal, mapa_email
        )
        patch["status"] = status
        patch["motivo_bloqueio"] = motivo
        patch["auditoria"] = (
            f"{item.get('auditoria', '')} | LLM: regex={tipo_regex} -> {sugestao_llm}"
        ).strip(" |")
        patch["motivo_alocacao"] = calcular_acondicionamento_e_restricoes(pedido, motor.params)

        revisao, motivo_q, palavra_q = avaliar_quarentena(
            float(item.get("peso_kg") or 0),
            item.get("observacao_comercial", ""),
            pedido.descricao_item,
            pedido.aprendizado_aplicado,
        )
        revisao = config.COD_REVISAO_OBRIGATORIA
        motivo_ia = f"Classificação sugerida pela IA: {sugestao_llm}"
        motivo_q = f"{motivo_q} | {motivo_ia}".strip(" |") if motivo_q else motivo_ia
        patch["revisao_obrigatoria"] = revisao
        patch["motivo_quarentena"] = motivo_q
        patch["palavra_chave_quarentena"] = palavra_q
        patch["auditoria"] = (
            f"{patch['auditoria']} | {config.COD_REVISAO_OBRIGATORIA}: {motivo_q}"
        ).strip(" |")
    else:
        patch["flag_revisao_llm"] = "NAO"

    return patch


def processar_fila_llm_inline(motor: MotorIngestao) -> int:
    """Processa fila IA in-memory (modo CLI, sem session store)."""
    ingest = motor.para_dict()
    pendentes = [c for c in ingest.get("consolidados", []) if c.get("status_ia") == config.COD_PROCESSANDO_IA]
    if not pendentes:
        return 0

    mapa_pdf = _indexar_pedidos_pdf(ingest.get("pedidos_pdf", []))
    mapa_fiscal = motor._indexar_retencoes()  # noqa: SLF001
    mapa_email = motor._indexar_eventos_email()  # noqa: SLF001

    consolidados_map = {
        _pedido_key(c): i for i, c in enumerate(ingest.get("consolidados", []))
    }

    processados = 0
    for item in pendentes:
        chave = _pedido_key(item)
        pedido_pdf = mapa_pdf.get(chave, {})
        if not pedido_pdf:
            idx = consolidados_map.get(chave)
            if idx is not None:
                motor.consolidados[idx].status_ia = config.STATUS_IA_ERRO
            processados += 1
            continue

        patch = _aplicar_llm_no_item(motor, item, pedido_pdf, mapa_fiscal, mapa_email)
        idx = consolidados_map.get(chave)
        if idx is not None:
            cons = motor.consolidados[idx]
            for k, v in patch.items():
                setattr(cons, k, v)
            # Sincroniza pedido PDF se tipo_frete mudou
            if "tipo_frete" in patch:
                for p in motor.pedidos_pdf:
                    if p.numero_pedido_norm == chave or p.numero_pedido == chave:
                        p.tipo_frete = patch["tipo_frete"]
                        p.flag_revisao_llm = patch.get("flag_revisao_llm", "NAO")
                        p.sugestao_llm_status = patch.get("sugestao_llm_status", "")
                        p.status_ia = patch.get("status_ia", config.STATUS_IA_CONCLUIDO)
                        break
        processados += 1

    return processados


def processar_fila_llm(session_id: str) -> int:
    """Processa pedidos PROCESSANDO_IA da sessão. Retorna quantidade processada."""
    ingest = store.load_ingestao(session_id)
    if not ingest:
        return 0

    consolidados = ingest.get("consolidados", [])
    pendentes = [c for c in consolidados if c.get("status_ia") == config.COD_PROCESSANDO_IA]
    if not pendentes:
        return 0

    session_dir = store.session_path(session_id)
    motor = MotorIngestao(str(session_dir))
    motor.pedidos_pdf = [_dict_to_pedido(p) for p in ingest.get("pedidos_pdf", [])]
    motor.retencoes_xlsb = [
        RetencaoFiscal(**{k: r.get(k, "") for k in RetencaoFiscal.__dataclass_fields__})
        for r in ingest.get("retencoes_xlsb", [])
    ]
    motor.eventos_email = [
        EventoEmail(**{k: e.get(k, "") for k in EventoEmail.__dataclass_fields__})
        for e in ingest.get("eventos_email", [])
    ]
    mapa_pdf = _indexar_pedidos_pdf(ingest.get("pedidos_pdf", []))
    mapa_fiscal = motor._indexar_retencoes()  # noqa: SLF001
    mapa_email = motor._indexar_eventos_email()  # noqa: SLF001

    processados = 0
    for item in pendentes:
        chave = _pedido_key(item)
        pedido_pdf = mapa_pdf.get(chave, {})
        if not pedido_pdf:
            store.update_consolidado(
                session_id,
                chave,
                {"status_ia": config.STATUS_IA_ERRO},
            )
            processados += 1
            continue

        patch = _aplicar_llm_no_item(motor, item, pedido_pdf, mapa_fiscal, mapa_email)
        store.update_consolidado(session_id, chave, patch)
        processados += 1

    return processados


def tem_pendentes_ia(payload: dict[str, Any]) -> bool:
    return any(
        c.get("status_ia") == config.COD_PROCESSANDO_IA for c in payload.get("consolidados", [])
    )
