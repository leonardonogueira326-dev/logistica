"""Números que o operador vê precisam bater com o que o motor decide."""
from __future__ import annotations

from models import PedidoFaturamento
from motor_ingestao import MotorIngestao
from motor_logistica import MotorLogistica


def _itens(*cidades_clientes):
    return [
        {"cidade_destino": cidade, "cliente_codigo": cli, "rota_logistica": "ROTA_CAPITAL", "peso_kg": 100}
        for cidade, cli in cidades_clientes
    ]


def test_tempo_do_card_e_o_mesmo_que_o_motor_usa():
    m = MotorLogistica()
    itens = _itens(("SAO PAULO", "1"), ("SAO PAULO", "2"), ("DIADEMA", "3"))
    assert m.calcular_teo(itens) == m.calcular_tempo_rota(itens)


def test_tempo_conta_paradas_e_nao_soma_ida_e_volta_de_cada_cidade():
    m = MotorLogistica()
    m.params.update(
        {"tempos_viagem_cidade_min": {"SAO PAULO": 240, "DIADEMA": 210}, "tempo_descarga_minutos": 20,
         "tempo_almoco_minutos": 60, "tempo_entre_cidades_min": 20}
    )
    itens = _itens(("SAO PAULO", "1"), ("SAO PAULO", "1"), ("DIADEMA", "3"))
    # max(240, 210) + 1 cidade extra x 20 + 2 paradas x 20 + 60 almoço
    assert m.calcular_tempo_rota(itens) == 240 + 20 + 40 + 60


def test_cadastro_nao_troca_a_cidade_de_entrega_do_pdf():
    motor = object.__new__(MotorIngestao)
    motor.avisos = []
    registro = {"codigo": "1234", "cidade": "SANTA BARBARA D OESTE", "bairro": "CENTRO",
                "cep": "13450-000", "latitude": -22.75, "longitude": -47.41}
    motor._cadastro_geo = {"registros": [registro], "indice_por_codigo": {"1234": registro}}
    p = PedidoFaturamento(cliente_codigo="01234", cidade_destino="GUARULHOS", cidade="GUARULHOS")
    motor._aplicar_cadastro_geolocalizado(p)
    assert p.cidade_destino == "GUARULHOS"
    assert any("mantido o destino do PDF" in a for a in motor.avisos)
