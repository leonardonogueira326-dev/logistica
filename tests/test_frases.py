"""Dicionário de frases: conhecida x nova, ensinar, aplicar."""
from __future__ import annotations

from frases import AVISAR, ENTREGAR_ATE, FRETE, analisar, chave, ensinar, frete_ensinado, quebrar, sugestao

OBS_AEF = ("LOGISTICA - ENTREGAR ATÉ 06/11/26 CONFORME COMBINADO COM O CLIENTE NA TRANSPORTADORA - "
           "Redução do DECRETO Nº 11.055, DE 28 DE ABRIL DE 2022 - ENVIAR BOLETOS VIA EMAIL PARA: X@Y.COM.BR")


def test_quebra_e_coringas():
    frases = quebrar(OBS_AEF)
    assert any("ENTREGAR ATÉ 06/11/26" in f for f in frases)
    assert all("DECRETO" not in f for f in frases)
    assert chave("ENTREGAR ATÉ 06/11/26 NA TRANSP") == chave("Entregar até 15/12/2026 na transp")


def test_boleto_e_horario_sao_conhecidos_por_regra():
    r = analisar("ENVIAR BOLETOS VIA EMAIL PARA: A@B.COM - RECEBIMENTO SEG A SEX DAS 7:30 AS 16HS", {})
    assert [x["situacao"] for x in r] == ["REGRA", "REGRA"]


def test_frase_de_logistica_desconhecida_e_nova_com_sugestao():
    (x,) = analisar("ENVIAR EM CAIXAS DE MADEIRA", {})
    assert x["situacao"] == "NOVA" and x["sugestao"] == AVISAR
    assert sugestao("ENTREGAR ATÉ 06/11/26 CONFORME COMBINADO")[0] == ENTREGAR_ATE


def test_ensinar_vale_para_outras_datas_e_aplica_frete(tmp_path):
    arq = tmp_path / "frases.json"
    k = chave("REPRESENTANTE LEVA NO CLIENTE")
    ensinar(k, "REPRESENTANTE LEVA NO CLIENTE", FRETE, "RETIRA FOB", arq)
    import json

    dic = json.loads(arq.read_text())
    (x,) = analisar("REPRESENTANTE LEVA NO CLIENTE", dic)
    assert x["situacao"] == "OPERADOR"
    assert frete_ensinado("PEDIDO URGENTE - REPRESENTANTE LEVA NO CLIENTE", dic) == "RETIRA_FOB"
    # parecida (uma palavra a mais) também vale
    assert analisar("REPRESENTANTE LEVA NO CLIENTE HOJE", dic)[0]["situacao"] in ("OPERADOR", "NOVA")
