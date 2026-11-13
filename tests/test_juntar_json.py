"""Aprendizado dos dois PCs junto, item por item (scripts/juntar_json.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import juntar_json as jj  # noqa: E402


def test_cada_pc_ensinou_uma_coisa():
    base = {"_versao": "1"}
    casa = {"_versao": "1", "123_FORT": "TERCEIRO"}
    empresa = {"_versao": "1", "456_LAP": "RETIRA FOB"}
    assert jj.juntar(base, casa, empresa) == {"_versao": "1", "456_LAP": "RETIRA FOB", "123_FORT": "TERCEIRO"}


def test_mesmo_item_diferente_fica_o_deste_pc_e_apagado_sai():
    base = {"a": 1, "b": 2, "c": 3}
    nuvem = {"a": 10, "b": 2}  # mudou a, apagou c
    pc = {"a": 20, "b": 2, "c": 3, "d": 4}  # mudou a, criou d
    assert jj.juntar(base, nuvem, pc) == {"a": 20, "b": 2, "d": 4}


def test_itens_aninhados_e_listas():
    base = {"motoristas": ["ISRAEL"], "cli": {"1": {"abre": "08:00"}}}
    nuvem = {"motoristas": ["ISRAEL", "JOAO"], "cli": {"1": {"abre": "08:00"}, "2": {"abre": "07:00"}}}
    pc = {"motoristas": ["ISRAEL", "LEONARDO"], "cli": {"1": {"abre": "08:30"}}}
    r = jj.juntar(base, nuvem, pc)
    assert r["motoristas"] == ["ISRAEL", "LEONARDO", "JOAO"]
    assert r["cli"] == {"1": {"abre": "08:30"}, "2": {"abre": "07:00"}}


def test_lista_de_registros_por_id():
    base = {"frota": [{"id": "A", "ativo": True}, {"id": "B", "ativo": True}]}
    nuvem = {"frota": [{"id": "A", "ativo": False}, {"id": "B", "ativo": True}]}
    pc = {"frota": [{"id": "A", "ativo": True}, {"id": "B", "ativo": True}, {"id": "C", "ativo": True}]}
    r = jj.juntar(base, nuvem, pc)["frota"]
    assert {x["id"]: x["ativo"] for x in r} == {"A": False, "B": True, "C": True}


def test_arquivo_criado_nos_dois_pcs_sem_base():
    assert jj.juntar(jj._FALTA, {"x": 1}, {"y": 2}) == {"y": 2, "x": 1}


def test_so_junta_json_direto_em_data(tmp_path, monkeypatch):
    assert jj.pode_juntar("data/frases.json") and jj.pode_juntar("data\\geocache.json")
    assert not jj.pode_juntar("data/sessions/abc/roteirizacao.json")
    assert not jj.pode_juntar("base-de-clientes.xlsx")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    for nome, dados in (("b", {"a": 1}), ("n", {"a": 1, "casa": "ç"}), ("p", {"a": 1, "empresa": 2})):
        (tmp_path / nome).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    assert jj.main(["x", "data/frases.json", "b", "n", "p"]) == 0
    assert json.loads((tmp_path / "data/frases.json").read_text(encoding="utf-8")) == {"a": 1, "empresa": 2, "casa": "ç"}
    assert jj.main(["x", "data/sessions/s/ingestao.json", "b", "n", "p"]) == 3
    (tmp_path / "p").write_text("{quebrado", encoding="utf-8")
    assert jj.main(["x", "data/frases.json", "b", "n", "p"]) == 5
