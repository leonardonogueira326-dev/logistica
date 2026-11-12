"""Remessa / NF triangular: o destino físico vem da observação."""
from __future__ import annotations

from destino_entrega import detectar_entrega
from motor_logistica import MotorLogistica

OBS_FORT = (
    "CLIENTE NAO ACEITA REPASSE DE TÍTULOS A TERCEIROS - EMITIR NF TRIAGULAR E ENTREGAR NA EMPRESA "
    "FORT LAMINAÇÃO. NOME: Fort Laminação de Perfis Ltda - ME CNPJ: 23.470.265/0001-59 I.E. "
    "712.084.576.119 - ENDEREÇO RUA LUIZ OMETTO, 205 - DISTR. INDL. I - SANTA BARBARA D'OESTE"
)


def test_fort_pelo_endereco_da_observacao():
    d = detectar_entrega(OBS_FORT)
    assert d["cidade"] == "SANTA BARBARA D'OESTE"
    assert d["triangular"] == "SIM"
    assert d["origem"] == "observacao"


def test_fort_pela_base_de_clientes():
    base = {
        "777": {"codigo": "777", "razao_social": "FORT LAMINACAO DE PERFIS LTDA ME",
                "cidade": "SANTA BARBARA D OESTE", "bairro": "DISTRITO INDUSTRIAL", "cep": "13456-000"},
        "1": {"codigo": "1", "razao_social": "FILTROTEC EQUIPAMENTOS", "cidade": "BLUMENAU"},
    }
    d = detectar_entrega(OBS_FORT, base)
    assert (d["codigo"], d["cep"], d["origem"]) == ("777", "13456-000", "base")


def test_frases_comuns_nao_viram_destino():
    for obs in ("LEVAR NA TRANSPORTADORA KELLER", "FAVOR ENTREGAR NO PERIODO DA MANHA",
                "ENTREGAR SOMENTE APOS DIA 10", ""):
        assert detectar_entrega(obs) is None


def test_mistura_de_corredores_diz_quais_clientes():
    motor = MotorLogistica()
    motor.params["corredores_logisticos"] = {
        "1": {"nome": "Norte/Marginal", "prefixos_cep": ["02"]},
        "3": {"nome": "Sul/ABC", "prefixos_cep": ["09"]},
    }
    motor._cache_mapa_corredor = {}
    r = motor.verificar_efeito_elastico([
        {"cliente": "ZAGONEL S.A. (ZAGONEL)", "cep_destino": "02100-000"},
        {"cliente": "ATX TREFILADOS (ATX)", "cep_destino": "02200-000"},
        {"cliente": "BRIZANTE INDUSTRIA (BRIZANTE)", "cep_destino": "09000-000"},
    ])
    assert r["alerta_elastico"]
    assert r["mensagem_alerta_elastico"] == "Corredores misturados: Norte/Marginal (ZAGONEL, ATX) × Sul/ABC (BRIZANTE)"


def test_remessa_por_item_andritz():
    from destino_entrega import detectar_remessa_por_item

    obs = ("NOTAS FISCAIS DE REMESSA ... - ITEM 1 a 4 e 6 a 9 remessa LAP para mao de obra R$ 4,50 - "
           "ITEM 5 remessa FORT para mao de obra R$ 4,50 NF TRIANGULAR P/ IND BRAS DE CONES")
    base = {
        "3732": {"codigo": "3732", "razao_social": "FORT LAMINACAO DE PERFIS LTDA ME", "cidade": "SANTA BARBARA D OESTE",
                 "bairro": "DISTRITO INDUSTRIAL I", "cep": "13456-114"},
        "3262": {"codigo": "3262", "razao_social": "LAMINACAO DE ACOS PAULINIA LTDA EPP", "cidade": "PAULINIA",
                 "bairro": "PQ DA INDUSTRIA BETEL", "cep": "13148-374"},
    }
    assert detectar_remessa_por_item(obs, "005227/26/005", base)["codigo"] == "3732"
    assert detectar_remessa_por_item(obs, "005227/26/003", base)["codigo"] == "3262"
    assert detectar_remessa_por_item(obs, "005227/26/010", base) is None
    assert detectar_remessa_por_item("FAVOR ENTREGAR ITEM 2", "005227/26/002", base) is None


def test_remessa_ida_com_peso_zerado_e_volta_com_peso(tmp_path, monkeypatch):
    """Andritz /005 peso 0 -> vai para a FORT; Bruno /001 com 44 kg -> já voltou, segue o frete."""
    from models import PedidoFaturamento
    from motor_ingestao import MotorIngestao

    m = MotorIngestao(str(tmp_path))
    m._lookup_clientes = {
        "3732": {"codigo": "3732", "razao_social": "FORT LAMINACAO DE PERFIS LTDA ME", "cidade": "SANTA BARBARA D OESTE",
                 "bairro": "DISTRITO INDUSTRIAL I", "cep": "13456-114"},
    }
    obs = "REMESSA PARA INDUSTRIALIZAÇÃO: item 1 remessa para FORT mao de obra R$ 4,50"
    ida = PedidoFaturamento(numero_pedido="005227/26/001", peso_kg=0, observacao_comercial=obs, tipo_frete="RETIRA_FOB")
    volta = PedidoFaturamento(numero_pedido="005215/26/001", peso_kg=44, observacao_comercial=obs,
                              tipo_frete="ENTREGA_TERCEIRO_HUB")
    assert m._aplicar_remessa_industrializacao(ida)["codigo"] == "3732"
    assert ida.tipo_frete == "ENTREGA_DIRETA" and ida.industrializacao.startswith("Remessa")
    assert m._aplicar_remessa_industrializacao(volta) is None
    assert volta.tipo_frete == "ENTREGA_TERCEIRO_HUB" and volta.industrializacao.startswith("Voltou")


def test_remessa_com_erros_de_digitacao_do_pdf():
    """'tens 1 remessa para FORTmao de obra … tens 2 3 4 remessa para LAP' (Bruno, lista 09/11)."""
    from destino_entrega import detectar_remessa_por_item

    obs = "tens 1 remessa para FORTmao de obra R$ 4,65 - tens 2 3 4 remessa para LAP mao de obra R$ 4,50"
    base = {"1": {"codigo": "1", "razao_social": "FORT LAMINACAO DE PERFIS", "cidade": "SBO"},
            "2": {"codigo": "2", "razao_social": "LAMINACAO DE ACOS PAULINIA", "cidade": "PAULINIA"}}
    assert detectar_remessa_por_item(obs, "005061/26/001", base)["codigo"] == "1"
    assert detectar_remessa_por_item(obs, "005061/26/003", base)["codigo"] == "2"


def test_observacao_sem_parcelas_e_sem_totais_do_relatorio():
    """Parcelas (fonte menor) e 'Qtde. Itens / Preço Total' não entram na observação."""
    import os

    import pytest

    from extrator_pdf import ExtratorPDF

    pdf = "dados_teste/091102.pdf"
    if not os.path.exists(pdf):
        pytest.skip("sem o PDF de teste")
    obs = {p.numero_pedido: p.observacao_comercial for p in ExtratorPDF(pdf).extrair()}
    assert "5522,58" not in obs["005061/26/001"]
    assert "Qtde" not in obs["004521/26/002"] and "Preço Total" not in obs["004521/26/002"]
