"""Banco local: transação, espelho no arquivo, novidade do outro PC, versões e backup."""
from __future__ import annotations

import json
import os
import time

import pytest

import armazenamento as arm


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGISTICA_SEM_BANCO", raising=False)
    monkeypatch.delenv("LOGISTICA_SEM_ESPELHO", raising=False)
    monkeypatch.setattr(arm, "RAIZ", tmp_path)
    monkeypatch.setattr(arm, "ARQUIVO_DB", tmp_path / "data" / "local" / "logistica.db")
    monkeypatch.setattr(arm, "_backup_feito", "9999-99-99")  # sem backup em segundo plano no teste
    return tmp_path


def _mexer_por_fora(arq, dados):
    time.sleep(0.01)
    arq.write_text(json.dumps(dados) if not isinstance(dados, str) else dados, encoding="utf-8")
    os.utime(arq, ns=(time.time_ns(), time.time_ns() + 5_000_000))


def test_grava_no_banco_e_espelha_no_arquivo(banco):
    arq = banco / "data" / "frases.json"
    with pytest.raises(FileNotFoundError):
        arm.ler(arq)
    assert not arm.existe(arq) and arm.ler_ou(arq, {}) == {}
    arm.gravar(arq, {"a": "ç"})
    assert arm.ler(arq) == {"a": "ç"} and arm.existe(arq)
    assert json.loads(arq.read_text(encoding="utf-8")) == {"a": "ç"}
    assert not list(arq.parent.glob("*.gravando"))
    assert arm.status()["documentos"] == 1 and arm.status()["integridade"] == "ok"


def test_arquivo_que_ja_existia_entra_no_banco(banco):
    arq = banco / "data" / "aprendizado_regras.json"
    arq.parent.mkdir(parents=True)
    arq.write_text('{"1_FORT": "TERCEIRO"}', encoding="utf-8")
    assert arm.ler(arq) == {"1_FORT": "TERCEIRO"}
    assert arm.status()["ultima_alteracao"]["origem"] == "arquivo"


def test_novidade_do_outro_pc_chega_pela_sincronizacao(banco):
    arq = banco / "data" / "frases.json"
    arm.gravar(arq, {"a": 1})
    m1 = arm.marca(arq)
    _mexer_por_fora(arq, {"a": 1, "casa": 2})
    assert arm.ler(arq) == {"a": 1, "casa": 2}
    assert arm.marca(arq) != m1
    assert arm.status()["ultima_alteracao"]["origem"] == "sincronizacao"
    assert len(arm.versoes(arq)) == 1  # a versão anterior ficou guardada


def test_arquivo_corrompido_nao_entra_e_e_refeito(banco):
    arq = banco / "data" / "frases.json"
    arm.gravar(arq, {"a": 1})
    _mexer_por_fora(arq, '<<<<<<< HEAD\n{"a": 1,\n=======')
    assert arm.ler(arq) == {"a": 1}
    assert json.loads(arq.read_text(encoding="utf-8")) == {"a": 1}


def test_arquivo_apagado_por_fora_some_do_banco(banco):
    arq = banco / "data" / "sessions" / "s1" / "ingestao.json"
    arm.gravar(arq, {"consolidados": []})
    arq.unlink()
    assert not arm.existe(arq)
    with pytest.raises(FileNotFoundError):
        arm.ler(arq)


def test_espelho_que_falhou_e_refeito_depois(banco, monkeypatch):
    arq = banco / "data" / "frases.json"
    real = arm._gravar_arquivo
    monkeypatch.setattr(arm, "_gravar_arquivo", lambda c, t: (_ for _ in ()).throw(OSError("antivirus")))
    arm.gravar(arq, {"a": 1})
    assert not arq.exists() and arm.status()["espelhos_pendentes"] == 1
    assert arm.ler(arq) == {"a": 1}  # o banco tem o dado
    monkeypatch.setattr(arm, "_gravar_arquivo", real)
    assert arm.ler(arq) == {"a": 1}
    assert arq.exists() and arm.status()["espelhos_pendentes"] == 0


def test_versoes_e_restaurar(banco):
    arq = banco / "data" / "frases.json"
    for i in range(arm.VERSOES_GUARDADAS + 5):
        arm.gravar(arq, {"n": i})
    vs = arm.versoes(arq)
    assert len(vs) == arm.VERSOES_GUARDADAS
    arm.restaurar(arq, vs[1]["id"])
    assert arm.ler(arq) == {"n": arm.VERSOES_GUARDADAS + 2}
    arm.gravar(arq, {"n": "igual"})
    n = len(arm.versoes(arq))
    arm.gravar(arq, {"n": "igual"})  # gravar o mesmo conteúdo não cria versão
    assert len(arm.versoes(arq)) == n


def test_so_banco_nao_cria_arquivo_e_fora_da_pasta_so_arquivo(banco, tmp_path_factory):
    arq = banco / ".desfazer" / "s1.json"
    arm.gravar(arq, [1, 2], so_banco=True)
    assert arm.ler(arq) == [1, 2] and not arq.exists()
    arm.apagar(arq)
    assert not arm.existe(arq)
    fora = tmp_path_factory.mktemp("fora") / "x.json"
    arm.gravar(fora, {"z": 1})
    assert arm.ler(fora) == {"z": 1} and arm.status()["documentos"] == 0


def test_backup(banco):
    arm.gravar(banco / "data" / "frases.json", {"a": 1})
    destino = arm.backup()
    assert destino and destino.exists() and destino.stat().st_size > 0
    import sqlite3

    c = sqlite3.connect(destino)
    assert c.execute("SELECT COUNT(*) FROM documentos").fetchone()[0] == 1
    c.close()


def test_sem_espelho_o_banco_fica_sozinho(banco, monkeypatch):
    monkeypatch.setenv("LOGISTICA_SEM_ESPELHO", "1")
    arq = banco / "data" / "frases.json"
    arm.gravar(arq, {"a": 1})
    assert arm.ler(arq) == {"a": 1} and not arq.exists()
