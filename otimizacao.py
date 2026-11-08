"""
Sequência de entrega de um caminhão com Google OR-Tools.

- Paradas = clientes (vários pedidos do mesmo cliente/cidade são uma parada).
- Distância: linha reta x fator de estrada (1,3) — sem depender de internet.
  Tempo: distância / velocidade média + descarga por parada.
- Janela de recebimento lida da observação ("08:30 às 11:30") quando dá para
  entender; se não houver solução respeitando as janelas, resolve só pela
  distância e avisa.
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
    m = re.search(_HORA + r"\s*(?:at[ée]\s+[àa]s?|[àáa]s?|a|-|at[ée])\s+" + _HORA, texto or "", re.IGNORECASE)
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


def otimizar(
    paradas: list[dict[str, Any]],
    deposito: tuple[float, float],
    inicio_min: int = 7 * 60,
    velocidade_kmh: float = 40.0,
    descarga_min: int = 20,
    limite_seg: int = 5,
) -> dict[str, Any]:
    """
    paradas: [{"id", "lat", "lon", "janela": (ini, fim) | None}]
    Retorna {"ordem": [ids], "km_antes", "km_depois", "aviso"}.
    """
    com = [p for p in paradas if p.get("lat") is not None and p.get("lon") is not None]
    sem = [p for p in paradas if p not in com]
    aviso = f"{len(sem)} parada(s) sem localização ficaram no fim." if sem else ""

    def total_km(seq: list[dict[str, Any]]) -> float:
        pontos = [deposito] + [(p["lat"], p["lon"]) for p in seq] + [deposito]
        return sum(km(pontos[i], pontos[i + 1]) for i in range(len(pontos) - 1))

    km_antes = total_km(com)
    if len(com) <= 1:
        return {"ordem": [p["id"] for p in com + sem], "km_antes": round(km_antes, 1),
                "km_depois": round(km_antes, 1), "aviso": aviso}

    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    pontos = [deposito] + [(p["lat"], p["lon"]) for p in com]
    n = len(pontos)
    dist = [[int(km(pontos[i], pontos[j]) * 1000) for j in range(n)] for i in range(n)]  # metros
    minutos = [[int(dist[i][j] / 1000 / velocidade_kmh * 60) + (descarga_min if j else 0) for j in range(n)]
               for i in range(n)]

    def resolver(com_janelas: bool) -> Optional[list[int]]:
        gerente = pywrapcp.RoutingIndexManager(n, 1, 0)
        modelo = pywrapcp.RoutingModel(gerente)
        cb_dist = modelo.RegisterTransitCallback(
            lambda a, b: dist[gerente.IndexToNode(a)][gerente.IndexToNode(b)]
        )
        modelo.SetArcCostEvaluatorOfAllVehicles(cb_dist)
        if com_janelas:
            cb_tempo = modelo.RegisterTransitCallback(
                lambda a, b: minutos[gerente.IndexToNode(a)][gerente.IndexToNode(b)]
            )
            modelo.AddDimension(cb_tempo, 240, 24 * 60, False, "tempo")
            tempo = modelo.GetDimensionOrDie("tempo")
            tempo.CumulVar(modelo.Start(0)).SetRange(inicio_min, inicio_min)
            for no, p in enumerate(com, start=1):
                janela = p.get("janela")
                if janela:
                    tempo.CumulVar(gerente.NodeToIndex(no)).SetRange(max(janela[0], inicio_min), janela[1])
        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.seconds = limite_seg
        solucao = modelo.SolveWithParameters(params)
        if not solucao:
            return None
        ordem, idx = [], modelo.Start(0)
        while not modelo.IsEnd(idx):
            no = gerente.IndexToNode(idx)
            if no:
                ordem.append(no - 1)
            idx = solucao.Value(modelo.NextVar(idx))
        return ordem

    tem_janelas = any(p.get("janela") for p in com)
    ordem = resolver(True) if tem_janelas else None
    if ordem is None:
        if tem_janelas:
            aviso = ("Não deu para respeitar todos os horários de recebimento; sequência só pela distância. "
                     + aviso).strip()
        ordem = resolver(False) or list(range(len(com)))
    seq = [com[i] for i in ordem]
    return {"ordem": [p["id"] for p in seq + sem], "km_antes": round(km_antes, 1),
            "km_depois": round(total_km(seq), 1), "aviso": aviso}
