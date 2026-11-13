"""Kanban: soltar card parado num caminhão (consulta ao representante / travas)."""
from __future__ import annotations

from tests.conftest import trocar_no_quadro  # noqa: E402

import pytest
from fastapi import HTTPException

import api.routers.quadro_montagem as montagem
from api.schemas import MoverPedidoSchema
from models import PedidoConsolidado
from motor_logistica import MotorLogistica


def _linha(**campos) -> PedidoConsolidado:
    base = dict(
        numero_pedido="003060/26/001", id_item="003060/26/001#005037/26", cliente="MOLTEC",
        cliente_codigo="02305", peso_kg=150, cidade_destino="SAO PAULO", status="LIBERADO",
        representante="ELAINE ZANETTI", data_referencia="2026-06-19", data_producao="02/07/26",
        dias_uteis_antecedencia=9, rota_logistica="SP CAPITAL",
    )
    base.update(campos)
    return PedidoConsolidado(**base)


@pytest.fixture
def ambiente(monkeypatch):
    estado: dict = {"patches": []}

    def preparar(linha: PedidoConsolidado):
        # uma linha comum garante um caminhão em rota para SP
        comum = _linha(numero_pedido="009999/26/001", id_item="009999/26/001#009998/26",
                       cliente="OUTRO", cliente_codigo="99999", dias_uteis_antecedencia=0)
        motor = MotorLogistica()
        motor.alocar_frota([linha, comum])
        estado["veiculo"] = next(v for v, itens in motor.itens_por_veiculo.items() if itens)
        estado["rote"] = motor.para_dict()
        estado["linha"] = linha

    class FakeStore:
        def load_roteirizacao(self, sid):
            return estado["rote"]

        def save_roteirizacao(self, sid, data):
            estado["rote"] = data

    trocar_no_quadro(monkeypatch, "store", FakeStore())
    trocar_no_quadro(monkeypatch, "_get_active_consolidados", lambda sid: ({}, [estado["linha"]], True))
    trocar_no_quadro(monkeypatch, "_patch_consolidado_session", lambda sid, i, p: estado["patches"].append((i, p)) or True
    )
    estado["preparar"] = preparar
    return estado


def _no_caminhao(estado) -> bool:
    return any(
        i.get("id_item") == "003060/26/001#005037/26"
        for itens in estado["rote"]["itens_por_veiculo"].values()
        for i in itens
    )


def test_consulta_pendente_pede_confirmacao(ambiente):
    ambiente["preparar"](_linha())
    with pytest.raises(HTTPException) as e:
        montagem.mover_pedido("s", MoverPedidoSchema(numero_pedido="003060/26/001#005037/26", destino=ambiente["veiculo"]))
    assert e.value.status_code == 409
    assert not _no_caminhao(ambiente)


def test_representante_liberou_no_kanban_carrega_e_registra(ambiente):
    ambiente["preparar"](_linha())
    r = montagem.mover_pedido(
        "s",
        MoverPedidoSchema(
            numero_pedido="003060/26/001#005037/26", destino=ambiente["veiculo"],
            liberar_representante=True, autorizado_por="Elaine",
        ),
    )
    assert r.ok and _no_caminhao(ambiente)
    (_, patch), = ambiente["patches"]
    assert patch["consulta_representante"] == "LIBERADO"
    assert patch["representante_autorizou"] == "Elaine"


@pytest.mark.parametrize(
    "campos",
    [dict(liberacao_comercial="AGUARDANDO", dias_uteis_antecedencia=0), dict(peso_kg=0, dias_uteis_antecedencia=0)],
)
def test_linha_travada_nao_sobe_nem_forcando(ambiente, campos):
    ambiente["preparar"](_linha(**campos))
    with pytest.raises(HTTPException) as e:
        montagem.mover_pedido(
            "s",
            MoverPedidoSchema(
                numero_pedido="003060/26/001#005037/26", destino=ambiente["veiculo"],
                forcar=True, liberar_representante=True,
            ),
        )
    assert e.value.status_code == 400 and "Pendências" in e.value.detail
    assert not _no_caminhao(ambiente)
