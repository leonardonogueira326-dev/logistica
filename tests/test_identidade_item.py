"""
Identidade de uma linha: pedido/ano/item + OF.

Casos reais (PDF de 19/06):
- 003060/26/002 aparece 3x com OFs 003435/26, 008761/25 e 000001/26;
- o mesmo item+OF pode voltar outro dia com o saldo (300 kg hoje, 700 kg amanhã).
"""

import pytest

import historico_manager as hm
from models import PedidoConsolidado
from motor_logistica import MotorLogistica
from normalizador import mesma_linha, montar_id_item


def test_id_item_usa_pedido_e_of():
    assert montar_id_item("003060/26/002", "008761/25") == "003060/26/002#008761/25"
    assert montar_id_item("003060/26/002", "", "021") == "003060/26/002#SEQ021"
    assert montar_id_item("", "008761/25") == ""


def test_mesma_linha_nao_confunde_ofs():
    a = {"numero_pedido": "003060/26/002", "id_item": "003060/26/002#003435/26"}
    b = {"numero_pedido": "003060/26/002", "id_item": "003060/26/002#008761/25"}
    assert mesma_linha(b, "003060/26/002#008761/25")
    assert not mesma_linha(a, "003060/26/002#008761/25")
    # compatibilidade: nº puro ainda casa (chamadas antigas)
    assert mesma_linha(a, "003060/26/002")


def _linha(of: str, peso: float) -> PedidoConsolidado:
    return PedidoConsolidado(
        numero_pedido="003060/26/002",
        id_item=f"003060/26/002#{of}",
        of_ano=of,
        cliente="MOLTEC",
        cliente_codigo="02305",
        peso_kg=peso,
        cidade_destino="SAO PAULO",
        estado_destino="SAO PAULO",
        status="LIBERADO",
    )


def test_mover_uma_linha_nao_move_as_outras_ofs():
    linhas = [_linha("003435/26", 50), _linha("008761/25", 106), _linha("000001/26", 50)]
    motor = MotorLogistica()
    motor.alocar_frota(linhas)

    def onde(id_item):
        for vid, itens in motor.itens_por_veiculo.items():
            if any(i.id_carga == id_item for i in itens):
                return vid
        if any(b.get("id_carga") == id_item for b in motor.backlog):
            return "BACKLOG"
        if any(b.get("id_carga") == id_item for b in motor.backlog_local):
            return "LOCAL"
        return None

    antes = {l.id_item: onde(l.id_item) for l in linhas}
    assert all(antes.values()), antes

    alvo = "003060/26/002#008761/25"
    ok, _ = motor.mover_pedido(alvo, "BACKLOG", motivo="teste")
    assert ok
    assert onde(alvo) == "BACKLOG"
    for l in linhas:
        if l.id_item != alvo:
            assert onde(l.id_item) == antes[l.id_item], f"{l.id_item} mudou de lugar"


@pytest.fixture
def historico_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(hm, "HISTORICO_DIR", tmp_path)
    monkeypatch.setattr(hm, "_cache_hashes", None)
    monkeypatch.setattr(hm, "_cache_linhas", None)
    monkeypatch.setattr(hm, "_cache_por_item", None)
    return tmp_path


def _registro(sol: str, seq: str, peso: float) -> dict:
    return {
        "numero_pedido": "003002/26/001",
        "id_item": "003002/26/001#004938/26",
        "numero_solicitacao": sol,
        "seq_solicitacao": seq,
        "peso_kg": peso,
        "cliente": "MOLTEC",
        "cliente_codigo": "02305",
        "status": "LIBERADO",
    }


def test_saldo_do_mesmo_item_volta_no_dia_seguinte(historico_tmp):
    # Dia 1: sai 300 kg (solicitação 005723, linha 028)
    hm.arquivar_sessao("s1", [_registro("005723", "028", 300)], data_entrega="2026-06-19")

    # Mesmo PDF carregado de novo -> é repetição, pode descartar
    assert hm.linha_ja_arquivada("005723", "028", "003002/26/001#004938/26")

    # Dia 2: o saldo de 700 kg vem em OUTRA solicitação -> não é repetição
    assert not hm.linha_ja_arquivada("005724", "011", "003002/26/001#004938/26")
    anteriores = hm.programado_anteriormente("003002/26/001#004938/26")
    assert [r["peso_kg"] for r in anteriores] == [300]


def test_dois_dias_nao_se_sobrescrevem(historico_tmp):
    hm.arquivar_sessao("s1", [_registro("005723", "028", 300)], data_entrega="2026-06-19")
    hm.arquivar_sessao("s2", [_registro("005724", "011", 700)], data_entrega="2026-06-19")
    pesos = sorted(r["peso_kg"] for r in hm.programado_anteriormente("003002/26/001#004938/26"))
    assert pesos == [300, 700]
