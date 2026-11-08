"""
Quem precisa agir em cada linha.

- Consulta ao representante: SÓ quando a logística leva o material
  (frota própria ou levar na transportadora). Retira FOB e transportadora
  que coleta na fábrica não passam pela logística.
- Pagamento antecipado: qualquer frete, fica parado até o comercial liberar.
- Peso zerado: qualquer frete, a logística precisa informar o peso.
"""
from __future__ import annotations

import pytest

import config
from models import PedidoConsolidado
from pendencias import (
    CONSULTA_REPRESENTANTE,
    PAGAMENTO_ANTECIPADO,
    PESO_ZERADO,
    motivo_parado,
    pendencias,
)


def _linha(**campos) -> PedidoConsolidado:
    base = dict(peso_kg=150, status=config.COD_LIBERADO, dias_uteis_antecedencia=0, data_producao="02/07/26")
    base.update(campos)
    return PedidoConsolidado(**base)


@pytest.mark.parametrize(
    "status, consulta",
    [
        (config.COD_LIBERADO, True),        # frota própria: a logística leva
        (config.COD_TERCEIRO_HUB, True),    # levar na transportadora: a logística leva
        (config.COD_RETIRA_FOB, False),     # cliente retira
        (config.COD_TERCEIRO, False),       # transportadora coleta na fábrica
    ],
)
def test_consulta_ao_representante_so_quando_a_logistica_leva(status, consulta):
    abertas = pendencias(_linha(status=status, dias_uteis_antecedencia=9))
    assert (CONSULTA_REPRESENTANTE in abertas) is consulta


def test_menos_de_3_dias_uteis_nao_consulta():
    assert pendencias(_linha(dias_uteis_antecedencia=2)) == []
    assert pendencias(_linha(dias_uteis_antecedencia=-5)) == []  # Dt. Produção já passou


def test_representante_liberou_resolve_e_nao_liberou_segue_parado():
    assert pendencias(_linha(dias_uteis_antecedencia=9, consulta_representante="LIBERADO")) == []
    nao = _linha(dias_uteis_antecedencia=9, consulta_representante="NAO_LIBERADO")
    assert pendencias(nao) == [CONSULTA_REPRESENTANTE]
    assert "NÃO liberou" in motivo_parado(nao)


@pytest.mark.parametrize("status", [config.COD_LIBERADO, config.COD_RETIRA_FOB, config.COD_TERCEIRO])
def test_pagamento_antecipado_vale_para_qualquer_frete(status):
    assert PAGAMENTO_ANTECIPADO in pendencias(_linha(status=status, liberacao_comercial="AGUARDANDO"))
    assert PAGAMENTO_ANTECIPADO not in pendencias(_linha(status=status, liberacao_comercial="LIBERADO"))


@pytest.mark.parametrize("status", [config.COD_LIBERADO, config.COD_RETIRA_FOB, config.COD_TERCEIRO])
def test_peso_zerado_vale_para_qualquer_frete(status):
    assert PESO_ZERADO in pendencias(_linha(status=status, peso_kg=0))
    assert PESO_ZERADO not in pendencias(_linha(status=status, peso_kg=12.5))


def test_pendencias_se_somam():
    abertas = pendencias(_linha(dias_uteis_antecedencia=5, liberacao_comercial="AGUARDANDO", peso_kg=0))
    assert abertas == [CONSULTA_REPRESENTANTE, PAGAMENTO_ANTECIPADO, PESO_ZERADO]


def test_bloqueio_fiscal_nao_gera_outras_pendencias():
    assert pendencias(_linha(status=config.COD_BLOQUEIO_FISCAL, peso_kg=0, dias_uteis_antecedencia=9)) == []


def test_mudar_o_frete_na_conferencia_muda_a_regra():
    c = _linha(status=config.COD_RETIRA_FOB, dias_uteis_antecedencia=9)
    assert pendencias(c) == []
    c.status = config.COD_LIBERADO  # operador corrigiu: na verdade é frota própria
    assert pendencias(c) == [CONSULTA_REPRESENTANTE]
