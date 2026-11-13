"""Levar na transportadora: endereço da base > endereço do PDF > aviso de cadastro."""
from __future__ import annotations

import openpyxl
import pytest
from fastapi.testclient import TestClient

import transportadoras as tr
from geocodificacao import chave_da_linha


def _base(tmp_path, linhas, cab=("CODIGO", "NOME_FANTASIA", "ENDERECO", "NUMERO", "BAIRRO", "CIDADE", "UF", "CEP",
                                 "HORARIO_RECEBIMENTO")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Dados"
    ws.append(list(cab))
    for linha in linhas:
        ws.append(list(linha))
    wb.save(tmp_path / "base-transportadoras.xlsx")
    tr._cache.clear()
    return tr.carregar(tmp_path)


@pytest.mark.parametrize(
    "texto,cidade,endereco",
    [
        ("RODOVIASUL - RUA SOLDADO JOSE REYMAO, 105, SAO PAULO - 02178-040 - (11)2412-7843", "SAO PAULO",
         "RUA SOLDADO JOSE REYMAO, 105"),
        ("NOSTRA VIA - R DOS TUCANOS, 630, CARAPICUIBA", "CARAPICUIBA", "R DOS TUCANOS, 630"),
        ("GRIFE - RUA IRAQUARA, 24, GUARULHOS -", "GUARULHOS", "RUA IRAQUARA, 24"),
        # cortados no PDF: sem cidade (antes virava 'L B LOG' / 'R MONICA AP.' na coluna Cidade)
        ("L B LOG - R. HEROI DA FORCA EXPED. BRASILEIRA,", "", "R. HEROI DA FORCA EXPED. BRASILEIRA"),
        ("TRANSGOSS GT TRANSPORTES - R MONICA AP.", "", "R MONICA AP."),
        ("TRANSPORTADORA A DEFINIR - , - 00000-000 -", "", ""),
    ],
)
def test_endereco_do_pdf(texto, cidade, endereco):
    e = tr.endereco_do_pdf(texto)
    assert e["cidade"] == cidade and e["endereco"] == endereco


def test_base_vence_o_pdf_e_codigo_sem_zeros(tmp_path):
    base = _base(tmp_path, [(1168, "L B LOG", "R. HEROI DA FEB", "350", "VILA MARIA", "Sao Paulo", "SP", "02170-000",
                             "seg a sex 8h-17h")])
    info = tr.endereco_transportadora("01168", "L B LOG - R. HEROI DA FORCA EXPED. BRASILEIRA,", base)
    assert info["origem"] == "base" and info["cidade"] == "SAO PAULO" and info["endereco"] == "R. HEROI DA FEB, 350"
    campos = tr.campos_da_linha(info)
    assert campos["enriquecido_mestre"] == "HUB" and campos["cidade_destino"] == "SAO PAULO"
    assert campos["obs_recebimento"] == "Transportadora recebe: seg a sex 8h-17h"
    assert "VILA MARIA" in campos["entrega_em"]


def test_base_sem_endereco_usa_pdf_ou_avisa(tmp_path):
    base = _base(tmp_path, [(1073, "RODOVIASUL", None, None, None, None, None, None, None),
                            (1168, "L B LOG", None, None, None, None, None, None, None)])
    pdf = tr.endereco_transportadora("01073", "RODOVIASUL - RUA X, 105, SAO PAULO - 02178-040 -", base)
    assert pdf["origem"] == "pdf" and pdf["cidade"] == "SAO PAULO"
    nada = tr.endereco_transportadora("01168", "L B LOG - R. HEROI DA FORCA EXPED. BRASILEIRA,", base)
    assert nada["origem"] == "" and "cadastre" in tr.rotulo(nada) and "1168" in tr.rotulo(nada)
    assert tr.campos_da_linha(nada)["enriquecido_mestre"] == "NAO"


def test_base_atual_so_com_cnpj_e_telefone(tmp_path):
    base = _base(tmp_path, [(1168, "L B LOG TRANSPORTES LTDA", "L B LOG", "10.784.589/0002-09", "(11)2085-0019")],
                 cab=("CODIGO", "RAZAO_SOCIAL", "NOME_FANTASIA", "CNPJ", "TELEFONE"))
    info = tr.endereco_transportadora("01168", "L B LOG - R. HEROI,", base)
    assert info["origem"] == "" and info["telefone"] == "(11)2085-0019"


def test_mapa_localiza_a_transportadora(monkeypatch):
    monkeypatch.setattr(tr, "carregar", lambda pasta=None: {"1073": {"codigo": "1073", "nome": "RODOVIASUL",
                                                                     "cidade": "SAO PAULO", "endereco": "RUA X"}})
    linha = {"tipo_frete": "ENTREGA_TERCEIRO_HUB", "transportadora_codigo": "01073", "transportadora": "RODOVIASUL -",
             "cliente_codigo": "999", "cidade_destino": "SAO PAULO"}
    assert chave_da_linha(linha, {}) == "TRP:1073"
    assert chave_da_linha({**linha, "transportadora_codigo": "5", "transportadora": "X - R. Y,"}, {}) == ""


# ------------------------------------------------------------- troca manual na conferência
@pytest.fixture()
def quadro(tmp_path, monkeypatch):
    from api.main import app
    from api.routers import sessions as rs
    from api.session_store import store

    monkeypatch.setattr(store, "base_dir", tmp_path, raising=False)
    monkeypatch.setattr(rs, "endereco_transportadora", lambda cod, txt: tr.endereco_transportadora(cod, txt, {}))
    sid = store.create_session()
    linha = {
        "numero_pedido": "005285/26/001", "numero_pedido_norm": "005285/26/001", "id_item": "X#1",
        "cliente": "SUPRINDO", "cidade": "SAO PAULO", "cidade_destino": "SAO PAULO", "bairro_destino": "VL DOM PEDRO I",
        "status": "LIBERADO", "tipo_frete": "ENTREGA_DIRETA", "peso_kg": 120.0, "enriquecido_mestre": "SIM",
        "transportadora": "NOSTRA VIA - R DOS TUCANOS, 630, CARAPICUIBA", "transportadora_codigo": "00462",
        "obs_recebimento": "SÓ ABRE AS 8:00", "auditoria": "",
    }
    store.save_ingestao(sid, {"consolidados": [linha]})
    return TestClient(app), sid


def test_trocar_para_levar_na_transportadora_e_voltar(quadro):
    client, sid = quadro
    url = f"/api/sessions/{sid}/consolidados/X%231"
    c = client.patch(url, json={"status": "ENTREGA_TERCEIRO_HUB"}).json()
    assert c["cidade_destino"] == "CARAPICUIBA" and c["enriquecido_mestre"] == "HUB"
    assert c["entrega_em"].startswith("Transportadora NOSTRA VIA") and not c["obs_recebimento"]
    c = client.patch(url, json={"status": "LIBERADO"}).json()
    assert c["cidade_destino"] == "SAO PAULO" and c["bairro_destino"] == "VL DOM PEDRO I" and not c["entrega_em"]
    assert c["obs_recebimento"] == "SÓ ABRE AS 8:00"
