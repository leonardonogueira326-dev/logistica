"""Remessa para industrialização: detectada sozinha, escolhida na caixa de frete ou ensinada."""
from __future__ import annotations

from tests.conftest import trocar_no_quadro  # noqa: E402

import json

import pytest
from fastapi.testclient import TestClient

from destino_entrega import detectar_remessa_geral
from frases import INDUSTRIALIZACAO, analisar, chave, ensinar, industrializacao_ensinada

BASE = {
    "3732": {"codigo": "3732", "razao_social": "FORT LAMINACAO DE PERFIS LTDA ME", "cidade": "SANTA BARBARA D OESTE",
             "bairro": "DISTRITO INDUSTRIAL I", "cep": "13456-114"},
}
# Lista 12/11, BD 004773/26/001 (peso 0): "REMRESSA" escrito errado e sem número de item
OBS_BD = (
    "CLIENTE SÓ EFETUA PAGAMENTOS AS QUARTAS-FEIRANSÃO SERÁ ACEITO NEGOCIAÇÃO COM FACTORING - "
    "TRANSPORTADORA RETIRA NA SUPERFINE - Redução do DECRETO Nº 11.055, DE 28 DE ABRIL DE 2022 - "
    "PODE PARCIAL - PODE ANTECIPAR - REMRESSA P/ MÃO DE OBRA NA FORT LAMINACAO - Trefilar - Valor R$ 40,60/kg"
)


def test_remessa_sem_item_vale_para_o_pedido():
    d = detectar_remessa_geral(OBS_BD, BASE)
    assert d and d["nome"] == "FORT" and d["cidade"] == "SANTA BARBARA D OESTE" and d["codigo"] == "3732"


def test_remessa_por_item_nao_e_atropelada():
    assert detectar_remessa_geral("ITEM 1 a 4 remessa LAP - ITEM 5 remessa FORT para mao de obra", BASE) is None


@pytest.mark.parametrize("obs", ["ENTREGA EM FORTALEZA", "REMESSA DE AMOSTRA GRATIS", "MAO DE OBRA R$ 4,50"])
def test_sem_remessa_para_empresa_conhecida_nao_mexe(obs):
    assert detectar_remessa_geral(obs, BASE) is None


def test_frase_de_remessa_nao_e_ignorada():
    r = {x["texto"]: x for x in analisar(OBS_BD, {})}
    x = r["REMRESSA P/ MÃO DE OBRA NA FORT LAMINACAO"]
    assert x["situacao"] == "REGRA" and x["significado"] == INDUSTRIALIZACAO and x["status"] == "FORT"
    (nova,) = analisar("REMESSA P/ MAO DE OBRA NA METALURGICA XYZ", {})
    assert nova["situacao"] == "NOVA" and nova["sugestao"] == INDUSTRIALIZACAO


def test_ensinar_remessa(tmp_path):
    arq = tmp_path / "frases.json"
    frase = "MATERIAL SEGUE PARA TREFILAR NO TERCEIRO"
    with pytest.raises(ValueError):
        ensinar(chave(frase), frase, INDUSTRIALIZACAO, "", arq)
    ensinar(chave(frase), frase, INDUSTRIALIZACAO, "FORT", arq)
    dic = json.loads(arq.read_text())
    assert industrializacao_ensinada("URGENTE - " + frase, dic) == "FORT"


# ------------------------------------------------------------------ caixa de frete (API)
@pytest.fixture()
def quadro(tmp_path, monkeypatch):
    from api.main import app
    from api.routers import sessions as rs
    from api.session_store import store

    monkeypatch.setattr(store, "base_dir", tmp_path, raising=False)
    trocar_no_quadro(monkeypatch, "obter_lookup_clientes", lambda _p: BASE)
    sid = store.create_session()
    linha = {
        "numero_pedido": "004773/26/001", "numero_pedido_norm": "004773/26/001", "id_item": "004773/26/001#008080/26",
        "cliente": "BECTON DICKINSON", "cidade": "JUIZ DE FORA", "cidade_destino": "JUIZ DE FORA",
        "status": "RETIRA FOB", "tipo_frete": "RETIRA_FOB", "peso_kg": 0.0, "observacao_comercial": OBS_BD,
        "auditoria": "",
    }
    store.save_ingestao(sid, {"consolidados": [linha]})
    return TestClient(app), sid, store


def test_escolher_industrializacao_na_caixa_e_desfazer(quadro):
    client, sid, store = quadro
    url = f"/api/sessions/{sid}/consolidados/004773%2F26%2F001%23008080%2F26"
    r = client.patch(url, json={"remessa_industrializacao": "FORT"})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["status"] == "LIBERADO" and c["cidade_destino"] == "SANTA BARBARA D OESTE"
    assert c["industrializacao"] == "Remessa para industrialização: FORT"
    assert "PESO_ZERADO" in (client.get(f"/api/sessions/{sid}/consolidados").json()["consolidados"][0]["pendencias"])

    r = client.patch(url, json={"remessa_industrializacao": "", "status": "RETIRA FOB"})
    c = r.json()
    assert c["status"] == "RETIRA FOB" and c["cidade_destino"] == "JUIZ DE FORA" and not c["industrializacao"]


def test_ensinar_remessa_corrige_o_quadro(quadro, tmp_path, monkeypatch):
    import frases

    client, sid, store = quadro
    monkeypatch.setattr(frases, "ARQUIVO", tmp_path / "frases.json")
    monkeypatch.setattr(frases.ensinar, "__defaults__", ("", tmp_path / "frases.json"))
    data = store.load_ingestao(sid)
    data["consolidados"][0]["observacao_comercial"] = "MATERIAL SEGUE PARA TREFILAR NO TERCEIRO"
    store.save_ingestao(sid, data)
    k = chave("MATERIAL SEGUE PARA TREFILAR NO TERCEIRO")
    r = client.post(f"/api/sessions/{sid}/frases/ensinar",
                    json={"chave": k, "exemplo": "x", "significado": INDUSTRIALIZACAO, "status": "FORT"})
    assert r.status_code == 200 and r.json()["atualizados"] == 1, r.text
    c = store.load_ingestao(sid)["consolidados"][0]
    assert c["status"] == "LIBERADO" and c["cidade_destino"] == "SANTA BARBARA D OESTE"
