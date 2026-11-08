"""
Dias úteis (seg-sex, sem feriados) para a regra de consulta ao representante.

Feriados nacionais fixos + móveis (Carnaval, Sexta-feira Santa, Corpus Christi)
calculados pela data da Páscoa. Feriados locais (municipais/estaduais) podem
ser adicionados em parametros_operacionais.json -> "feriados_extras":
["2026-12-04", ...].
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Iterable


def _pascoa(ano: int) -> date:
    """Algoritmo de Meeus/Jones/Butcher (calendário gregoriano)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


@lru_cache(maxsize=32)
def feriados_nacionais(ano: int) -> frozenset[date]:
    pascoa = _pascoa(ano)
    fixos = [
        (1, 1),    # Confraternização Universal
        (4, 21),   # Tiradentes
        (5, 1),    # Dia do Trabalho
        (9, 7),    # Independência
        (10, 12),  # Nossa Senhora Aparecida
        (11, 2),   # Finados
        (11, 15),  # Proclamação da República
        (11, 20),  # Dia Nacional de Zumbi e da Consciência Negra
        (12, 25),  # Natal
    ]
    moveis = [
        pascoa - timedelta(days=48),  # Carnaval (segunda)
        pascoa - timedelta(days=47),  # Carnaval (terça)
        pascoa - timedelta(days=2),   # Sexta-feira Santa
        pascoa + timedelta(days=60),  # Corpus Christi
    ]
    return frozenset([date(ano, m, d) for m, d in fixos] + moveis)


def _extras(extras: Iterable[str] | None) -> set[date]:
    out: set[date] = set()
    for texto in extras or []:
        try:
            out.add(datetime.strptime(str(texto).strip(), "%Y-%m-%d").date())
        except ValueError:
            continue
    return out


def eh_dia_util(dia: date, feriados_extras: Iterable[str] | None = None) -> bool:
    if dia.weekday() >= 5:
        return False
    if dia in feriados_nacionais(dia.year):
        return False
    return dia not in _extras(feriados_extras)


def dias_uteis_ate(
    referencia: date, alvo: date, feriados_extras: Iterable[str] | None = None
) -> int:
    """
    Quantos dias úteis faltam de `referencia` até `alvo` (sem contar a referência).
    Ex.: sexta -> segunda seguinte = 1. Negativo quando o alvo já passou.
    """
    if alvo == referencia:
        return 0
    passo = 1 if alvo > referencia else -1
    extras = list(feriados_extras or [])
    contagem, dia = 0, referencia
    while dia != alvo:
        dia += timedelta(days=passo)
        if eh_dia_util(dia, extras):
            contagem += passo
    return contagem


def parse_data_br(texto: str) -> date | None:
    """'02/07/26' ou '02/07/2026' ou '2026-07-02' -> date."""
    texto = (texto or "").strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None
