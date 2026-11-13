"""'TRANSPORTADORA A DEFINIR': a linha fica no representante até ele liberar e dizer qual é."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import transportadoras as tr
from pendencias import CONSULTA_REPRESENTANTE, motivo_parado, pendencias, transportadora_a_definir

PDF = "TRANSPORTADORA A DEFINIR - , - 00000-000 -"
BASE = {"1073": {"codigo": "1073", "nome": "RODOVIASUL", "endereco": "RUA X", "numero": "105",
                 "cidade": "SAO PAULO", "uf": "SP", "cep": "02178-040"}}


def _linha(**extra):
    linha = {
        "numero_pedido": "005237/26/001", "numero_pedido_norm": "005237/26/001", "id_item": "005237/26/001#008325/26",
        "cliente": "RP MOLAS", "representante": "THIARA - CERCA", "status": "ENTREGA_TERCEIRO_HUB",
        "tipo_frete": "ENTREGA_TERCEIRO_HUB", "peso_kg": 100.0, "dias_uteis_antecedencia": 0,
        "transportadora": PDF, "transportadora_codigo": "01110", "enriquecido_mestre": "NAO", "auditoria": "",
    }
    linha.update(extra)
    return linha


@pytest.mark.parametrize(
    "texto,esperado",
    [(PDF, True), ("TRANSP. A COMBINAR", True), ("A DEFINIR", True), ("RODOVIASUL - RUA X", False),
     ("DEFINITIVA TRANSPORTES", False), ("", False)],
)
def test_reconhece_a_definir(texto, esperado):
    assert tr.a_definir(texto) is esperado


def test_rotulo_nao_pede_cadastro():
    info = tr.endereco_transportadora("01110", PDF, {})
    assert tr.rotulo(info) == "Transportadora a definir — aguardando o representante informar"


def test_fica_no_representante_ate_liberar():
    linha = _linha()
    assert transportadora_a_definir(linha)
    assert pendencias(linha) == [CONSULTA_REPRESENTANTE]
    assert motivo_parado(linha) == "Consultar representante: transportadora a definir"
    # com Dt. Produção longe também: uma pendência só
    assert pendencias(_linha(dias_uteis_antecedencia=5)) == [CONSULTA_REPRESENTANTE]
    assert "NÃO liberou" in motivo_parado(_linha(consulta_representante="NAO_LIBERADO"))
    assert pendencias(_linha(consulta_representante="LIBERADO")) == []


def test_so_vale_para_levar_na_transportadora():
    assert pendencias(_linha(status="LIBERADO", tipo_frete="ENTREGA_DIRETA")) == []
    assert pendencias(_linha(status="TERCEIRO", tipo_frete="ENTREGA_TERCEIRO")) == []
    assert pendencias(_linha(transportadora="RODOVIASUL - RUA X, 105, SAO PAULO")) == []


@pytest.fixture()
def quadro(tmp_path, monkeypatch):
    from api.main import app
    from api.routers import sessions as rs
    from api.session_store import store

    monkeypatch.setattr(store, "base_dir", tmp_path, raising=False)
    monkeypatch.setattr(rs, "carregar_transportadoras", lambda: BASE)
    sid = store.create_session()
    store.save_ingestao(sid, {"consolidados": [_linha()]})
    return TestClient(app), sid, store, rs


def test_conferencia_informa_a_transportadora(quadro):
    client, sid, _, _ = quadro
    url = f"/api/sessions/{sid}/consolidados/005237%2F26%2F001%23008325%2F26"
    c = client.patch(url, json={"transportadora_codigo": "1073"}).json()
    assert c["transportadora"] == "RODOVIASUL" and c["transportadora_codigo"] == "1073"
    assert c["cidade_destino"] == "SAO PAULO" and c["enriquecido_mestre"] == "HUB"
    assert "RUA X, 105" in c["entrega_em"]
    lista = client.get(f"/api/sessions/{sid}/consolidados").json()["consolidados"]
    assert lista[0]["pendencias"] == []


def test_codigo_fora_da_base(quadro):
    client, sid, _, _ = quadro
    url = f"/api/sessions/{sid}/consolidados/005237%2F26%2F001%23008325%2F26"
    r = client.patch(url, json={"transportadora_codigo": "9999"})
    assert r.status_code == 400 and "9999" in r.json()["detail"]


def test_ao_liberar_no_quadro_troca_a_copia_do_card(quadro):
    _, sid, store, rs = quadro
    card = {"id_carga": "005237/26/001#008325/26", "id_item": "005237/26/001#008325/26",
            "numero_pedido": "005237/26/001", "cidade_destino": "", "cidade": "", "entrega_em": "x",
            "enriquecido_mestre": "NAO", "transportadora": PDF, "transportadora_codigo": "01110",
            "pendencias": "CONSULTA_REPRESENTANTE"}
    store.save_roteirizacao(sid, {"rotas": [], "itens_por_veiculo": {}, "backlog": [], "backlog_futuro": [card],
                                  "backlog_local": []}, desfazivel=False)
    assert rs._definir_transportadora(sid, ["005237/26/001#008325/26@P1"], "01073") == ["005237/26/001#008325/26"]
    novo = store.load_roteirizacao(sid)["backlog_futuro"][0]
    assert novo["cidade_destino"] == "SAO PAULO" and novo["transportadora"] == "RODOVIASUL"
    assert novo["enriquecido_mestre"] == "HUB"
    # já definida: chamar de novo não mexe
    assert rs._definir_transportadora(sid, ["005237/26/001#008325/26"], "1073") == []
