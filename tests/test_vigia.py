"""Vigia: decide quando é seguro reiniciar e religa o servidor que caiu."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vigia  # noqa: E402


def _saude(segundos_atras: float) -> dict:
    quando = (datetime.now() - timedelta(seconds=segundos_atras)).isoformat(timespec="seconds")
    return {"banco": {"ultima_alteracao": {"quando": quando}}}


def test_so_reinicia_quando_ninguem_esta_gravando():
    assert not vigia.ocioso(_saude(10))
    assert vigia.ocioso(_saude(vigia.OCIOSO_S + 5))
    assert vigia.ocioso(None) and vigia.ocioso({}) and vigia.ocioso({"banco": {"ultima_alteracao": None}})


def test_telas_so_sao_refeitas_quando_o_codigo_muda(tmp_path, monkeypatch):
    monkeypatch.setattr(vigia, "RAIZ", tmp_path)
    assert not vigia.telas_prontas("abc")
    client = tmp_path / "route-genius-main" / "dist" / "client"
    client.mkdir(parents=True)
    (client / "_shell.html").write_text("x")
    assert not vigia.telas_prontas("abc")
    (client.parent / ".commit").write_text("abc\n")
    assert vigia.telas_prontas("abc") and not vigia.telas_prontas("def")
