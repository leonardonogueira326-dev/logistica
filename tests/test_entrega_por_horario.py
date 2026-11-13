"""Ordem de entrega: de fora para dentro, horário de recebimento e agenda prevista."""
from __future__ import annotations

import pytest

import horarios_clientes as hc
from otimizacao import hhmm, janela_recebimento, otimizar, simular

SBO = (-22.7536, -47.4136)
# 12/11: BAÚ 2 com DECKTEL (Jd Shangrilá), JPL (Pq Novo Mundo) e LCS (Ferraz, recebe 08:30–11:30)
DECKTEL = {"id": "DECKTEL", "lat": -23.700, "lon": -46.700, "janela": (8 * 60, 17 * 60)}
JPL = {"id": "JPL", "lat": -23.515, "lon": -46.575, "janela": (8 * 60, 17 * 60)}
LCS = {"id": "LCS", "lat": -23.540, "lon": -46.370, "janela": (8 * 60 + 30, 11 * 60 + 30)}


def test_saindo_430_comeca_por_ferraz_e_volta_entregando():
    r = otimizar([DECKTEL, JPL, LCS], SBO, inicio_min=4 * 60 + 30, velocidade_kmh=30,
                 velocidade_estrada_kmh=75, descarga_min=20)
    assert r["ordem"][0] == "LCS"
    lcs = r["agenda"]["paradas"][0]
    assert lcs["chegada"] < 8 * 60 + 30 and lcs["espera"] > 0  # chega antes de abrir e é o primeiro
    assert all(a["atraso"] == 0 for a in r["agenda"]["paradas"])


def test_sem_de_fora_para_dentro_vale_so_distancia():
    r = otimizar([DECKTEL, JPL, LCS], SBO, inicio_min=4 * 60 + 30, velocidade_kmh=30,
                 velocidade_estrada_kmh=75, fator_afastar=0)
    assert sorted(r["ordem"]) == ["DECKTEL", "JPL", "LCS"]


def test_simular_espera_e_atraso():
    perto = {"id": "A", "lat": -22.74, "lon": -47.33, "janela": (9 * 60, 10 * 60)}
    ag = simular([perto], SBO, 7 * 60, 40, 20, 80)
    a = ag["paradas"][0]
    assert a["chegada"] < 9 * 60 and a["espera"] == 9 * 60 - a["chegada"] and a["atraso"] == 0
    assert ag["volta"] > 9 * 60 + 20
    tarde = simular([{**perto, "janela": (6 * 60, 7 * 60)}], SBO, 7 * 60, 40, 20, 80)["paradas"][0]
    assert tarde["atraso"] > 0
    assert hhmm(270) == "04:30"


@pytest.mark.parametrize("texto,janela", [("8h-17h", (480, 1020)), ("seg a sex 08:00 às 17:00", (480, 1020))])
def test_horarios_curtos(texto, janela):
    assert janela_recebimento(texto) == janela


def test_horario_do_cliente_entre_observacao_e_padrao(tmp_path):
    arq = tmp_path / "h.json"
    with pytest.raises(ValueError):
        hc.salvar("00123", "de manhã", arq)
    hc.salvar("00123", "09:00 às 16:00", arq)
    mem = hc.carregar(arq)
    assert mem == {"123": "09:00 às 16:00"}
    assert hc.janela_da_parada({"cliente_codigo": "123"}, mem) == ((540, 960), "cliente")
    obs = {"cliente_codigo": "123", "obs_recebimento": "SÓ ABRE AS 7:00"}
    assert hc.janela_da_parada(obs, mem)[1] == "observacao"
    assert hc.janela_da_parada({"cliente_codigo": "9"}, mem, "07:30 às 16:00") == ((450, 960), "padrao")
    hc.salvar("123", "", arq)
    assert hc.carregar(arq) == {}
