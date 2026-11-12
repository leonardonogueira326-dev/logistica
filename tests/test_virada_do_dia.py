"""O que não saiu ontem entra no quadro de hoje com 'pendente desde'."""
from __future__ import annotations

from virada_do_dia import juntar_ao_quadro_novo, pendentes_do_quadro


def _c(id_item, peso=100.0, status="LIBERADO", **extra):
    base = dict(id_item=id_item, numero_pedido=id_item.split("#")[0], peso_kg=peso, status=status,
                data_referencia="2026-06-17", data_producao="25/06/26", cliente="X")
    base.update(extra)
    return base


ROTE = {
    "itens_por_veiculo": {
        "BAU_1": [{"id_item": "A#1", "peso_kg": 100}, {"id_carga": "B#1@P1", "peso_kg": 300}],
        "BAU_2": [{"id_item": "C#1", "peso_kg": 50}],
    },
    "itens_retorno_por_veiculo": {},
    "veiculos_nao_sairam": ["BAU_2"],
}


def test_so_passa_o_que_nao_saiu():
    ontem = [
        _c("A#1"),                       # saiu inteira
        _c("B#1", peso=1000),            # saiu 300 de 1000 -> passam 700
        _c("C#1", peso=50),              # caminhão não saiu -> passa
        _c("D#1", peso=0),               # peso zerado sem tratativa -> passa
        _c("E#1", status="RETIRA FOB"),  # retira: não é da logística
        _c("F#1", status="TERCEIRO"),    # transportadora coleta
        _c("G#1", pendente_desde="2026-06-15"),  # já vinha de antes: mantém a data
    ]
    p = {x["id_item"]: x for x in pendentes_do_quadro(ontem, ROTE)}
    assert set(p) == {"B#1", "C#1", "D#1", "G#1"}
    assert p["B#1"]["peso_kg"] == 700
    assert p["C#1"]["pendente_desde"] == "2026-06-17"
    assert p["G#1"]["pendente_desde"] == "2026-06-15"


def test_sem_quadro_montado_passa_tudo_da_logistica():
    p = pendentes_do_quadro([_c("A#1"), _c("E#1", status="RETIRA FOB")], None)
    assert [x["id_item"] for x in p] == ["A#1"]


def test_pdf_novo_com_a_mesma_linha_nao_duplica_e_herda_decisoes():
    hoje = [_c("B#1", peso=700, data_referencia="2026-06-18", liberacao_comercial="AGUARDANDO"), _c("Z#1")]
    ontem = [dict(_c("B#1"), pendente_desde="2026-06-17", liberacao_comercial="LIBERADO",
                  liberacao_comercial_por="Ana"), _c("D#1", peso=0, pendente_desde="2026-06-17")]
    juntos, trazidas, herdadas = juntar_ao_quadro_novo(hoje, ontem, "2026-06-18")
    por_id = {c["id_item"]: c for c in juntos}
    assert (trazidas, herdadas, len(juntos)) == (1, 1, 3)
    assert por_id["B#1"]["peso_kg"] == 700 and por_id["B#1"]["pendente_desde"] == "2026-06-17"
    assert por_id["B#1"]["liberacao_comercial"] == "LIBERADO"
    d = por_id["D#1"]
    assert d["data_referencia"] == "2026-06-18"
    assert d["dias_uteis_antecedencia"] == 5  # 18/06 -> 25/06/26 (19/06 sexta ... 25/06 quinta)
    assert "VEIO DO DIA ANTERIOR" in d["auditoria"]
