"""
Pendências que seguram uma linha fora da rota até alguém agir.

Calculadas sempre a partir do estado ATUAL da linha (se o operador muda o
frete na conferência, a regra acompanha).

| Pendência              | Vale para                         | Quem resolve                     |
|------------------------|-----------------------------------|----------------------------------|
| CONSULTA_REPRESENTANTE | só frete da logística: frota      | representante: "pode carregar?"  |
|                        | própria e levar na transportadora |                                  |
|                        | + levar na transportadora com     | representante: libera e diz qual |
|                        |   "TRANSPORTADORA A DEFINIR"      | é a transportadora               |
| PAGAMENTO_ANTECIPADO   | só frete da logística             | comercial libera por e-mail      |
| PESO_ZERADO            | só frete da logística             | logística informa o peso         |

Retira FOB e transportadora que coleta na fábrica não passam pela logística:
nenhuma pendência (o comercial trata direto com o cliente / a transportadora).
"""

from __future__ import annotations

from typing import Any

import config
from transportadoras import a_definir

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


def transportadora_a_definir(c: Any) -> bool:
    """Levar na transportadora, mas o PDF diz 'TRANSPORTADORA A DEFINIR'."""
    return _get(c, "status") == config.COD_TERCEIRO_HUB and a_definir(str(_get(c, "transportadora", "")))


def logistica_age(c: Any) -> bool:
    return _get(c, "status") in STATUS_LOGISTICA


def pendencias(c: Any, limite_dias_uteis: int = 3) -> list[str]:
    """Códigos das pendências abertas desta linha (vazio = pode seguir)."""
    abertas: list[str] = []
    if str(_get(c, "status")) == config.COD_BLOQUEIO_FISCAL:
        return abertas  # já está bloqueada por outro motivo
    if not logistica_age(c):
        return abertas  # retira / transportadora coleta: a logística não age
    try:
        dias = int(_get(c, "dias_uteis_antecedencia", 0) or 0)
    except (TypeError, ValueError):
        dias = 0
    if _get(c, "consulta_representante") != "LIBERADO" and (
        dias >= limite_dias_uteis or transportadora_a_definir(c)
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
        if codigo == CONSULTA_REPRESENTANTE and transportadora_a_definir(c):
            situacao = " (representante NÃO liberou)" if _get(c, "consulta_representante") == "NAO_LIBERADO" else ""
            partes.append(f"Consultar representante: transportadora a definir{situacao}")
        elif codigo == CONSULTA_REPRESENTANTE:
            prod = _get(c, "data_producao")
            dias = _get(c, "dias_uteis_antecedencia")
            situacao = " (representante NÃO liberou)" if _get(c, "consulta_representante") == "NAO_LIBERADO" else ""
            partes.append(f"Consultar representante: Dt. Produção {prod} ({dias} dias úteis){situacao}")
        else:
            partes.append(DESCRICAO[codigo])
    return " | ".join(partes)
