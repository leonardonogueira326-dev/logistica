"""
Virada do dia: o que não saiu ontem entra no quadro de hoje.

Ao abrir o quadro de um dia novo, olhamos o quadro do dia anterior:
- linha (ou parte dela) que estava num caminhão que SAIU -> foi entregue, fica no histórico;
- caminhão marcado "não saiu" -> a carga dele volta;
- o resto que é da logística (pendências, parados, sobras, entregas locais) passa
  para o quadro novo com "pendente desde dd/mm";
- retira e transportadora que coleta não passam pela logística -> não passam.

Se o PDF novo já trouxe a mesma linha (pedido/item + OF), não duplica: a linha
nova fica, herdando o "pendente desde" e as decisões já tomadas (representante
liberou, comercial liberou).
"""
from __future__ import annotations

from typing import Any

from dias_uteis import dias_uteis_ate, parse_data_br

STATUS_FORA_DA_LOGISTICA = {"RETIRA FOB", "TERCEIRO"}
DECISOES = (
    "consulta_representante", "consulta_em", "consulta_obs", "representante_autorizou",
    "motivo_adiantamento", "liberacao_comercial", "liberacao_comercial_por",
    "liberacao_comercial_em", "liberacao_comercial_obs",
)


def _id(c: dict[str, Any]) -> str:
    return str(c.get("id_item") or c.get("id_carga") or c.get("numero_pedido") or "").split("@")[0]


def _f(v: Any) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def peso_que_saiu(rote: dict[str, Any] | None) -> dict[str, float]:
    """kg por linha que estava em caminhão que saiu (1ª e 2ª viagem)."""
    if not rote:
        return {}
    nao_sairam = set(rote.get("veiculos_nao_sairam") or [])
    saiu: dict[str, float] = {}
    for grupo in ("itens_por_veiculo", "itens_retorno_por_veiculo"):
        for vid, itens in (rote.get(grupo) or {}).items():
            if vid in nao_sairam:
                continue
            for it in itens:
                saiu[_id(it)] = saiu.get(_id(it), 0.0) + _f(it.get("peso_kg"))
    return saiu


def pendentes_do_quadro(consolidados: list[dict[str, Any]], rote: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Linhas do quadro anterior que NÃO saíram (com o peso que falta)."""
    saiu = peso_que_saiu(rote)
    ficam: list[dict[str, Any]] = []
    for c in consolidados:
        if str(c.get("status") or "") in STATUS_FORA_DA_LOGISTICA:
            continue
        total = _f(c.get("peso_kg"))
        resto = total - saiu.get(_id(c), 0.0)
        if total > 0 and resto <= 0.5:
            continue  # saiu inteira
        linha = dict(c)
        if total > 0:
            linha["peso_kg"] = round(resto, 2)
        linha["pendente_desde"] = c.get("pendente_desde") or c.get("data_referencia") or ""
        ficam.append(linha)
    return ficam


def juntar_ao_quadro_novo(
    novos: list[dict[str, Any]],
    pendentes: list[dict[str, Any]],
    data_referencia: str,
    feriados: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """
    Devolve (consolidados do quadro novo, quantas vieram de ontem, quantas
    já estavam no PDF novo e só herdaram o "pendente desde").
    """
    por_id = {_id(c): c for c in novos}
    trazidas = herdadas = 0
    resultado = list(novos)
    ref = parse_data_br(data_referencia) if data_referencia else None
    for p in pendentes:
        atual = por_id.get(_id(p))
        if atual is not None:
            atual["pendente_desde"] = p.get("pendente_desde", "")
            for campo in DECISOES:
                if p.get(campo) and (not atual.get(campo) or p.get(campo) == "LIBERADO"):
                    atual[campo] = p[campo]
            herdadas += 1
            continue
        linha = dict(p)
        if data_referencia:
            linha["data_referencia"] = data_referencia
            prod = parse_data_br(str(linha.get("data_producao") or ""))
            if ref and prod:
                linha["dias_uteis_antecedencia"] = dias_uteis_ate(ref, prod, feriados or [])
        linha["auditoria"] = (str(linha.get("auditoria") or "") + f" | VEIO DO DIA ANTERIOR (pendente desde {linha.get('pendente_desde', '')})").strip(" |")
        resultado.append(linha)
        por_id[_id(linha)] = linha
        trazidas += 1
    return resultado, trazidas, herdadas
