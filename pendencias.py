"""
Pendências que seguram uma linha fora da rota até alguém agir.

Calculadas sempre a partir do estado ATUAL da linha (se o operador muda o
frete na conferência, a regra acompanha).

| Pendência              | Vale para                         | Quem resolve                     |
|------------------------|-----------------------------------|----------------------------------|
| CONSULTA_REPRESENTANTE | só frete da logística: frota      | representante: "pode carregar?"  |
|                        | própria e levar na transportadora |                                  |
| PAGAMENTO_ANTECIPADO   | qualquer frete                    | comercial libera por e-mail      |
| PESO_ZERADO            | qualquer frete                    | logística informa o peso         |

Retira FOB e transportadora que coleta na fábrica não passam pela logística,
então não pedem consulta ao representante.
"""

from __future__ import annotations

from typing import Any

import config

CONSULTA_REPRESENTANTE = "CONSULTA_REPRESENTANTE"
PAGAMENTO_ANTECIPADO = "PAGAMENTO_ANTECIPADO"
PESO_ZERADO = "PESO_ZERADO"

# Fretes em que a logística leva o material (frota própria / levar na transportadora)
STATUS_LOGISTICA = frozenset({config.COD_LIBERADO, config.COD_TERCEIRO_HUB})

DESCRICAO = {
    CONSULTA_REPRESENTANTE: "Consultar representante",
    PAGAMENTO_ANTECIPADO: "Pagamento antecipado — aguardando liberação do comercial",
    PESO_ZERADO: "Peso zerado — informar o peso",
}


def _get(c: Any, campo: str, padrao: Any = "") -> Any:
    return c.get(campo, padrao) if isinstance(c, dict) else getattr(c, campo, padrao)


def logistica_age(c: Any) -> bool:
    return _get(c, "status") in STATUS_LOGISTICA


def pendencias(c: Any, limite_dias_uteis: int = 3) -> list[str]:
    """Códigos das pendências abertas desta linha (vazio = pode seguir)."""
    abertas: list[str] = []
    if str(_get(c, "status")) == config.COD_BLOQUEIO_FISCAL:
        return abertas  # já está bloqueada por outro motivo
    try:
        dias = int(_get(c, "dias_uteis_antecedencia", 0) or 0)
    except (TypeError, ValueError):
        dias = 0
    if (
        logistica_age(c)
        and dias >= limite_dias_uteis
        and _get(c, "consulta_representante") != "LIBERADO"
    ):
        abertas.append(CONSULTA_REPRESENTANTE)
    if _get(c, "liberacao_comercial") == "AGUARDANDO":
        abertas.append(PAGAMENTO_ANTECIPADO)
    try:
        peso = float(_get(c, "peso_kg", 0) or 0)
    except (TypeError, ValueError):
        peso = 0.0
    if peso <= 0:
        abertas.append(PESO_ZERADO)
    return abertas


def motivo_parado(c: Any, limite_dias_uteis: int = 3) -> str:
    partes = []
    for codigo in pendencias(c, limite_dias_uteis):
        if codigo == CONSULTA_REPRESENTANTE:
            prod = _get(c, "data_producao")
            dias = _get(c, "dias_uteis_antecedencia")
            situacao = " (representante NÃO liberou)" if _get(c, "consulta_representante") == "NAO_LIBERADO" else ""
            partes.append(f"Consultar representante: Dt. Produção {prod} ({dias} dias úteis){situacao}")
        else:
            partes.append(DESCRICAO[codigo])
    return " | ".join(partes)
