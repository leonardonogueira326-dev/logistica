"""
Sequência de entrega de um caminhão com Google OR-Tools.

- Paradas = clientes (vários pedidos do mesmo cliente/cidade são uma parada).
- Distância: linha reta x fator de estrada (1,3) — sem depender de internet.
  Tempo: distância / velocidade média + descarga por parada.
- Toda parada tem janela de recebimento: a da observação ("08:30 às 11:30"),
  senão a salva para o cliente, senão o recebimento padrão da Mesa de Comando.
- Tempo: estrada (fábrica -> 1ª parada e volta, de madrugada) numa velocidade,
  cidade (entre clientes) em outra.
- Objetivo: "de fora para dentro" — começa pela parada mais longe da fábrica
  e vai voltando para casa (se afastar de novo depois de começar custa caro),
  respeitando o horário de recebimento (chegou antes de abrir: espera).
- Chegar depois do fechamento é permitido com penalidade (avisa).
- Paradas sem coordenada ficam no fim, na ordem atual (e são avisadas).
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional

FATOR_ESTRADA = 1.3


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distância em km (haversine) x fator de estrada."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h)) * FATOR_ESTRADA


_HORA = r"(\d{1,2})\s*(?:[:h]\s*(\d{2}))?\s*h?\w*"


def janela_recebimento(texto: str) -> Optional[tuple[int, int]]:
    """Primeira faixa 'HH:MM ... HH:MM' do texto, em minutos do dia. Ex.: (510, 690)."""
    m = re.search(
        _HORA + r"\s*(?:(?:at[ée]\s+[àa]s?|[àáa]s?|a|at[ée])\s+|-\s*|às\s+)" + _HORA, texto or "", re.IGNORECASE
    )
    if not m:
        m2 = re.search(r"ABRE\s+[ÀA]S?\s*" + _HORA, texto or "", re.IGNORECASE)
        if m2:
            ini = int(m2.group(1)) * 60 + int(m2.group(2) or 0)
            return (ini, 18 * 60) if 0 < ini < 18 * 60 else None
        return None
    ini = int(m.group(1)) * 60 + int(m.group(2) or 0)
    fim = int(m.group(3)) * 60 + int(m.group(4) or 0)
    if not (0 < ini < fim <= 24 * 60):
        return None
    return ini, fim


def hhmm(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def simular(
    seq: list[dict[str, Any]],
    deposito: tuple[float, float],
    inicio_min: int,
    velocidade_kmh: float,
    descarga_min: int,
    velocidade_estrada_kmh: float | None = None,
) -> dict[str, Any]:
    """Horário previsto de cada parada na ordem dada (chegada, espera, atraso) e a volta."""
    estrada = velocidade_estrada_kmh or velocidade_kmh
    t, pos, out = inicio_min, deposito, []
    for p in seq:
        if p.get("lat") is None or p.get("lon") is None:
            out.append({"id": p["id"], "chegada": None, "espera": 0, "atraso": 0, "janela": p.get("janela")})
            continue
        vel = estrada if pos == deposito else velocidade_kmh
        chegada = t + int(round(km(pos, (p["lat"], p["lon"])) / vel * 60))
        janela = p.get("janela")
        inicio = max(chegada, janela[0]) if janela else chegada
        atraso = max(0, inicio - janela[1]) if janela else 0
        out.append({"id": p["id"], "chegada": chegada, "espera": inicio - chegada, "atraso": atraso, "janela": janela})
        t, pos = inicio + descarga_min, (p["lat"], p["lon"])
    volta = t + int(round(km(pos, deposito) / estrada * 60)) if pos != deposito else inicio_min
    return {"paradas": out, "saida": inicio_min, "volta": volta}


def otimizar(
    paradas: list[dict[str, Any]],
    deposito: tuple[float, float],
    inicio_min: int = 7 * 60,
    velocidade_kmh: float = 40.0,
    descarga_min: int = 20,
    limite_seg: int = 5,
    velocidade_estrada_kmh: float | None = None,
    fator_afastar: float = 2.0,
) -> dict[str, Any]:
    """
    paradas: [{"id", "lat", "lon", "janela": (ini, fim) | None}]
    Retorna {"ordem": [ids], "km_antes", "km_depois", "aviso", "agenda"}.
    """
    com = [p for p in paradas if p.get("lat") is not None and p.get("lon") is not None]
    sem = [p for p in paradas if p not in com]
    aviso = f"{len(sem)} parada(s) sem localização ficaram no fim." if sem else ""

    def total_km(seq: list[dict[str, Any]]) -> float:
        pontos = [deposito] + [(p["lat"], p["lon"]) for p in seq] + [deposito]
        return sum(km(pontos[i], pontos[i + 1]) for i in range(len(pontos) - 1))

    def resultado(seq: list[dict[str, Any]], aviso_: str) -> dict[str, Any]:
        agenda = simular(seq + sem, deposito, inicio_min, velocidade_kmh, descarga_min, velocidade_estrada_kmh)
        atrasados = [a for a in agenda["paradas"] if a["atraso"] > 0]
        if atrasados:
            aviso_ = (f"{len(atrasados)} parada(s) chegam depois do horário de recebimento. " + aviso_).strip()
        return {"ordem": [p["id"] for p in seq + sem], "km_antes": round(km_antes, 1),
                "km_depois": round(total_km(seq), 1), "aviso": aviso_, "agenda": agenda}

    km_antes = total_km(com)
    if len(com) <= 1:
        return resultado(com, aviso)

    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    pontos = [deposito] + [(p["lat"], p["lon"]) for p in com]
    n = len(pontos)
    dist = [[int(km(pontos[i], pontos[j]) * 1000) for j in range(n)] for i in range(n)]  # metros
    estrada = velocidade_estrada_kmh or velocidade_kmh
    # tempo i -> j = descarga em i (se é cliente) + viagem (estrada quando sai/volta da fábrica)
    minutos = [
        [
            (descarga_min if i else 0)
            + int(round(dist[i][j] / 1000 / (estrada if 0 in (i, j) else velocidade_kmh) * 60))
            for j in range(n)
        ]
        for i in range(n)
    ]
    # custo = km + penalidade por se afastar da fábrica entre um cliente e outro ("de fora para dentro")
    custo = [
        [
            (dist[i][j] + (int(fator_afastar * max(0, dist[0][j] - dist[0][i])) if i and j else 0)) // 100
            for j in range(n)
        ]
        for i in range(n)
    ]

    gerente = pywrapcp.RoutingIndexManager(n, 1, 0)
    modelo = pywrapcp.RoutingModel(gerente)
    cb_custo = modelo.RegisterTransitCallback(lambda a, b: custo[gerente.IndexToNode(a)][gerente.IndexToNode(b)])
    modelo.SetArcCostEvaluatorOfAllVehicles(cb_custo)
    cb_tempo = modelo.RegisterTransitCallback(lambda a, b: minutos[gerente.IndexToNode(a)][gerente.IndexToNode(b)])
    modelo.AddDimension(cb_tempo, 24 * 60, 48 * 60, False, "tempo")
    tempo = modelo.GetDimensionOrDie("tempo")
    tempo.CumulVar(modelo.Start(0)).SetRange(inicio_min, inicio_min)
    tempo.SetSpanCostCoefficientForAllVehicles(1)  # entre opções parecidas, a que volta mais cedo
    for no, p in enumerate(com, start=1):
        janela = p.get("janela")
        if janela:
            idx = gerente.NodeToIndex(no)
            tempo.CumulVar(idx).SetMin(max(janela[0], inicio_min))  # antes de abrir: espera
            tempo.SetCumulVarSoftUpperBound(idx, janela[1], 100000)  # depois de fechar: penalidade alta
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = limite_seg
    solucao = modelo.SolveWithParameters(params)
    if not solucao:
        return resultado(com, ("Não consegui otimizar; mantive a ordem atual. " + aviso).strip())
    ordem, idx = [], modelo.Start(0)
    while not modelo.IsEnd(idx):
        no = gerente.IndexToNode(idx)
        if no:
            ordem.append(no - 1)
        idx = solucao.Value(modelo.NextVar(idx))
    return resultado([com[i] for i in ordem], aviso)
