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
