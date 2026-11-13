"""Versão do código: este PC está igual ao GitHub?"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from api import versao_codigo as vc


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture()
def repos(tmp_path: Path):
    nuvem = tmp_path / "nuvem.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(nuvem))
    pc = tmp_path / "pc"
    _git(tmp_path, "clone", "-q", str(nuvem), str(pc))
    _git(pc, "config", "user.email", "t@t")
    _git(pc, "config", "user.name", "t")
    (pc / "a.txt").write_text("1")
    _git(pc, "add", "a.txt")
    _git(pc, "commit", "-qm", "c1")
    _git(pc, "push", "-q", "origin", "HEAD:main")
    vc._cache.update(commit="", quando=0.0, consultando=False)
    yield nuvem, pc, tmp_path
    vc._cache.update(commit="", quando=0.0, consultando=False)


def _esperar_consulta():
    for _ in range(100):
        if not vc._cache["consultando"]:
            return
        time.sleep(0.05)


def test_em_dia(repos):
    _, pc, _ = repos
    rodando = vc.commit_no_disco(pc)
    assert len(rodando) == 7
    vc.commit_github(pc)
    _esperar_consulta()
    s = vc.situacao(pc, rodando)
    assert s["github"] == rodando
    assert not s["atras_do_github"] and not s["desatualizado"]


def test_github_andou_e_o_pc_ficou_para_tras(repos):
    nuvem, pc, tmp = repos
    rodando = vc.commit_no_disco(pc)
    outro = tmp / "outro"
    _git(tmp, "clone", "-q", str(nuvem), str(outro))
    _git(outro, "config", "user.email", "t@t")
    _git(outro, "config", "user.name", "t")
    (outro / "b.txt").write_text("2")
    _git(outro, "add", "b.txt")
    _git(outro, "commit", "-qm", "c2")
    _git(outro, "push", "-q", "origin", "HEAD:main")
    novo = _git(outro, "rev-parse", "--short=7", "HEAD")

    vc.commit_github(pc)
    _esperar_consulta()
    s = vc.situacao(pc, rodando)
    assert s["github"] == novo
    assert s["atras_do_github"] is True


def test_sem_rede_usa_o_ultimo_fetch(repos, monkeypatch):
    _, pc, _ = repos
    _git(pc, "fetch", "-q", "origin")
    esperado = _git(pc, "rev-parse", "--short=7", "origin/main")
    monkeypatch.setattr(vc, "_consultar_github", lambda raiz: vc._cache.update(consultando=False, quando=time.time()))
    assert vc.commit_github(pc) == esperado


def test_status_do_script(tmp_path: Path):
    assert vc.status_atualizacao(tmp_path)["estado"] == ""
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "codigo_status.txt").write_text(
        "ERRO|13/11/2026 08:50|Nao consegui atualizar o codigo - detalhes em logs\\codigo.log\n"
    )
    st = vc.status_atualizacao(tmp_path)
    assert st["estado"] == "ERRO"
    assert st["quando"] == "13/11/2026 08:50"
    assert "codigo.log" in st["mensagem"]


def test_endpoint_versao():
    from fastapi.testclient import TestClient

    from api.main import app

    r = TestClient(app).get("/api/versao")
    assert r.status_code == 200
    corpo = r.json()
    for chave in ("rodando", "no_disco", "github", "desatualizado", "atras_do_github", "atualizacao"):
        assert chave in corpo
