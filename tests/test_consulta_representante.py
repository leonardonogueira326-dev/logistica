"""
Pedidos com Dt. Produção a 3 dias ÚTEIS ou mais da data do PDF ficam parados
até o representante liberar ("podemos carregar hoje?").
Dt. Produção no passado ou próxima: sai normalmente.
"""

from datetime import date

import pytest

from dias_uteis import dias_uteis_ate, eh_dia_util, feriados_nacionais, parse_data_br
from models import PedidoConsolidado, PedidoFaturamento
from motor_ingestao import MotorIngestao
from motor_logistica import MotorLogistica
from representantes import limpar_representante_pdf

SEXTA = date(2026, 6, 19)  # Data para Faturamento do PDF de 19/06


@pytest.mark.parametrize(
    "alvo, esperado",
    [
        (date(2026, 6, 22), 1),   # sexta -> segunda: 1 dia útil (3 corridos)
        (date(2026, 6, 24), 3),   # quarta: 3 dias úteis -> consulta
        (date(2026, 7, 2), 9),
        (date(2026, 6, 18), -1),  # Dt. Produção já passou
        (SEXTA, 0),
    ],
)
def test_dias_uteis(alvo, esperado):
    assert dias_uteis_ate(SEXTA, alvo) == esperado


def test_feriados_nacionais_2026_incluem_moveis():
    f = feriados_nacionais(2026)
    assert {date(2026, 2, 16), date(2026, 2, 17), date(2026, 4, 3), date(2026, 6, 4)} <= f
    assert date(2026, 11, 20) in f  # Consciência Negra (nacional desde 2024)


def test_feriado_nao_conta_como_dia_util():
    # 03/06/2026 (qua) -> 08/06/2026 (seg): quinta 04/06 é Corpus Christi
    assert dias_uteis_ate(date(2026, 6, 3), date(2026, 6, 8)) == 2
    assert not eh_dia_util(date(2026, 6, 4))
    assert not eh_dia_util(date(2026, 6, 4), ["2026-06-04"])
    assert not eh_dia_util(date(2026, 6, 5), ["2026-06-05"])  # feriado local configurado


def test_parse_data_br():
    assert parse_data_br("02/07/26") == date(2026, 7, 2)
    assert parse_data_br("2026-07-02") == date(2026, 7, 2)
    assert parse_data_br("") is None


def _motor_ingestao_minimo() -> MotorIngestao:
    m = object.__new__(MotorIngestao)
    m.params = {"antecedencia_consulta_dias_uteis": 3}
    return m


@pytest.mark.parametrize(
    "dt_producao, consulta",
    [("02/07/26", "PENDENTE"), ("24/06/26", "PENDENTE"), ("23/06/26", ""), ("22/06/26", ""), ("10/06/26", "")],
)
def test_regra_tres_dias_uteis(dt_producao, consulta):
    item = PedidoConsolidado(status="LIBERADO")
    pedido = PedidoFaturamento(data_faturamento="19/06/26", data_producao=dt_producao)
    _motor_ingestao_minimo()._aplicar_regra_consulta(item, pedido)
    assert item.consulta_representante == consulta
    assert item.data_referencia == "2026-06-19"
    if consulta:
        assert item.data_prevista_recebimento == parse_data_br(dt_producao).isoformat()
        assert "Consultar representante" in item.motivo_atraso


def test_bloqueio_fiscal_nao_vai_para_consulta():
    item = PedidoConsolidado(status="BLOQUEIO FISCAL")
    pedido = PedidoFaturamento(data_faturamento="19/06/26", data_producao="02/07/26")
    _motor_ingestao_minimo()._aplicar_regra_consulta(item, pedido)
    assert item.consulta_representante == ""


def test_motor_usa_data_do_pdf_e_nao_o_relogio():
    # Mesmo reprocessando o PDF de junho em novembro, a linha de 02/07 fica parada.
    c = PedidoConsolidado(
        numero_pedido="003060/26/001", id_item="003060/26/001#005037/26", cliente="MOLTEC",
        cliente_codigo="02305", peso_kg=150, cidade_destino="SAO PAULO", status="LIBERADO",
        representante="ELAINE ZANETTI", data_referencia="2026-06-19",
        data_prevista_recebimento="2026-07-02", consulta_representante="PENDENTE",
        motivo_atraso="Consultar representante: Dt. Produção 02/07/2026 (9 dias úteis)",
    )
    motor = MotorLogistica()
    motor.alocar_frota([c])
    assert [b["id_item"] for b in motor.backlog_futuro] == ["003060/26/001#005037/26"]
    b = motor.backlog_futuro[0]
    assert b["representante"] == "ELAINE ZANETTI" and b["consulta_representante"] == "PENDENTE"
    assert not any(motor.itens_por_veiculo.values())


def test_liberado_pelo_representante_entra_na_rota():
    c = PedidoConsolidado(
        numero_pedido="003060/26/001", id_item="003060/26/001#005037/26", cliente="MOLTEC",
        cliente_codigo="02305", peso_kg=150, cidade_destino="SAO PAULO", status="LIBERADO",
        data_referencia="2026-06-19", data_prevista_recebimento="", consulta_representante="LIBERADO",
    )
    motor = MotorLogistica()
    motor.alocar_frota([c])
    assert not motor.backlog_futuro
    assert any(i.id_item == c.id_item for itens in motor.itens_por_veiculo.values() for i in itens) or any(
        b.get("id_item") == c.id_item for b in motor.backlog_local
    )


@pytest.mark.parametrize(
    "bruto, limpo",
    [
        ("MARCOS CASTRO (TECNOACO) CONDIÇÃO DE PGTO: 14/21/28 DDL", "MARCOS CASTRO"),
        ("CARLA FIGUEREDO", "CARLA FIGUEREDO"),
        ("", ""),
    ],
)
def test_limpar_representante_do_pdf(bruto, limpo):
    assert limpar_representante_pdf(bruto) == limpo
