"""Qual versão do código este PC está rodando, e se ela é a mesma do GitHub.

- ``no_disco``: commit da pasta (lido direto do .git, sem precisar do git).
- ``github``: commit da main no GitHub. Consultado com ``git ls-remote`` em
  segundo plano, no máximo a cada 10 minutos; enquanto não houver resposta,
  usa o que o último ``git fetch`` deixou em refs/remotes/origin/main.
- ``logs/codigo_status.txt``: resultado do scripts/atualizar_codigo.bat.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

INTERVALO_GITHUB_S = 600

_lock = threading.Lock()
_cache: dict = {"commit": "", "quando": 0.0, "consultando": False}


def _ler_ref(git: Path, ref: str) -> str:
    arquivo = git / ref
    try:
        if arquivo.exists():
            return arquivo.read_text(encoding="utf-8").strip()[:7]
        packed = git / "packed-refs"
        if packed.exists():
            for linha in packed.read_text(encoding="utf-8").splitlines():
                if linha.endswith(" " + ref):
                    return linha[:7]
    except OSError:
        pass
    return ""


def commit_no_disco(raiz: Path) -> str:
    git = raiz / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if head.startswith("ref:"):
        return _ler_ref(git, head.split(" ", 1)[1].strip())
    return head[:7]


def _consultar_github(raiz: Path) -> None:
    commit = ""
    try:
        r = subprocess.run(
            ["git", "ls-remote", "origin", "refs/heads/estavel", "refs/heads/main"],
            cwd=raiz,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            # "estavel" = última versão em que os testes do GitHub passaram; sem ela, a main
            refs = {l.split()[1]: l.split()[0] for l in r.stdout.splitlines() if len(l.split()) == 2}
            commit = (refs.get("refs/heads/estavel") or refs.get("refs/heads/main", ""))[:7]
    except (OSError, subprocess.SubprocessError):
        pass
    with _lock:
        if commit:
            _cache["commit"] = commit
        _cache["quando"] = time.time()
        _cache["consultando"] = False


def commit_github(raiz: Path) -> str:
    """Último commit conhecido da main do GitHub ('' se nunca soube)."""
    with _lock:
        vencido = time.time() - _cache["quando"] > INTERVALO_GITHUB_S
        if vencido and not _cache["consultando"]:
            _cache["consultando"] = True
            threading.Thread(target=_consultar_github, args=(raiz,), daemon=True).start()
        conhecido = _cache["commit"]
    git = raiz / ".git"
    return conhecido or _ler_ref(git, "refs/remotes/origin/estavel") or _ler_ref(git, "refs/remotes/origin/main")


def status_atualizacao(raiz: Path) -> dict:
    """Resultado do último atualizar_codigo.bat: OK / SEMREDE / ERRO."""
    try:
        linha = (raiz / "logs" / "codigo_status.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"estado": "", "quando": "", "mensagem": ""}
    partes = linha.strip().split("|", 2)
    while len(partes) < 3:
        partes.append("")
    return {"estado": partes[0].strip(), "quando": partes[1].strip(), "mensagem": partes[2].strip()}


def situacao(raiz: Path, rodando: str) -> dict:
    no_disco = commit_no_disco(raiz)
    github = commit_github(raiz)
    return {
        "rodando": rodando,
        # ligado pelo vigia (ligar_sozinho.bat): ele mesmo atualiza e reinicia
        "vigia": bool(os.environ.get("LOGISTICA_VIGIA")),
        "no_disco": no_disco,
        "github": github,
        # código da pasta mudou depois que o servidor subiu
        "desatualizado": bool(rodando and no_disco and no_disco != rodando),
        # tem versão mais nova no GitHub do que a que está rodando
        "atras_do_github": bool(rodando and github and github != rodando),
        "atualizacao": status_atualizacao(raiz),
    }
