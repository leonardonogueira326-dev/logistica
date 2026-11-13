"""Fluxo do quadro do dia com o banco local ligado (sessão, desfazer, outro PC)."""
from __future__ import annotations

import json
import os
import time

import pytest

import armazenamento as arm
from api.session_store import SessionStore


@pytest.fixture()
def loja(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGISTICA_SEM_BANCO", raising=False)
    monkeypatch.setattr(arm, "RAIZ", tmp_path)
    monkeypatch.setattr(arm, "ARQUIVO_DB", tmp_path / "data" / "local" / "logistica.db")
    monkeypatch.setattr(arm, "_backup_feito", "9999-99-99")
    return SessionStore(tmp_path / "data" / "sessions"), tmp_path


def test_sessao_completa_no_banco(loja):
    store, raiz = loja
    sid = store.create_session()
    assert store.load_ingestao(sid) is None and store.load_roteirizacao(sid) is None
    store.save_ingestao(sid, {"consolidados": [{"id_item": "A#1", "numero_pedido": "A", "status": "LIBERADO"}]})
    assert store.update_consolidado(sid, "A#1", {"status": "TERCEIRO"})
    assert store.load_ingestao(sid)["consolidados"][0]["status"] == "TERCEIRO"
    store.set_validated(sid)
    assert store.is_validated(sid)
    assert [q["session_id"] for q in store.listar_quadros()] == [sid]
    # espelho para a sincronização
    arq = raiz / "data" / "sessions" / sid / "ingestao.json"
    assert json.loads(arq.read_text(encoding="utf-8"))["consolidados"][0]["status"] == "TERCEIRO"


def test_desfazer_fica_so_no_banco(loja):
    store, raiz = loja
    sid = store.create_session()
    store.save_roteirizacao(sid, {"v": 1})
    store.save_roteirizacao(sid, {"v": 2})
    store.save_roteirizacao(sid, {"v": 3})
    assert store.qtd_desfazer(sid) == 2
    assert store.desfazer_roteirizacao(sid) == {"v": 2}
    assert store.load_roteirizacao(sid) == {"v": 2}
    assert not (raiz / ".desfazer").exists()


def test_quadro_que_chegou_do_outro_pc(loja):
    store, raiz = loja
    sid = store.create_session()
    store.save_roteirizacao(sid, {"v": "empresa"})
    arq = raiz / "data" / "sessions" / sid / "roteirizacao.json"
    time.sleep(0.01)
    arq.write_text('{"v": "casa"}', encoding="utf-8")
    os.utime(arq, ns=(time.time_ns(), time.time_ns() + 5_000_000))
    assert store.load_roteirizacao(sid) == {"v": "casa"}
