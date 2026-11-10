"""Lista de carretéis / solda / cerca: peso por peça, levar na transp., representante."""
from __future__ import annotations

from extrator_pdf import REGEX_HUB_REDESPACHO, peso_por_peca_kg
from normalizador import extrair_cidade_transportadora


def test_peso_da_peca_na_descricao():
    assert peso_por_peca_kg("ARAME 304L 0,600mm 900GR - 0,600mm - PB") == 0.9
    assert peso_por_peca_kg("ARAME 304L 0,900mm 1KG - 0,900mm") == 1.0
    assert peso_por_peca_kg("SF AT E308LT1 1,20mm CRPLAST 12,5Kg") == 12.5
    assert peso_por_peca_kg("ESPONJA ACO INOX 10 GR C/50 UN") == 0.5  # caixa com 50
    assert peso_por_peca_kg("Redução do DECRETO Nº 11.055") == 0.0


def test_levar_na_transp_abreviado():
    for obs in ("LEVAR NA TRANSP", "LEVAR NA TRANSPORTADORA", "ENTREGAR NA TRANSP.", "DEIXAR NA TRANSPORTADORA"):
        assert REGEX_HUB_REDESPACHO.search(obs), obs


def test_cidade_da_transportadora_com_linha_quebrada():
    t = "RAPIDO FIGUEIREDO - R. OURO V. DE GOIAS, 1233, GUARULHOS - 07221-080 - (11)2487-7066"
    assert extrair_cidade_transportadora(t) == "GUARULHOS"
