"""
Sincronização dos dados entre os PCs (repositório privado logistica-dados).

GET  /api/sincronizacao  -> última sincronização deste PC (o .bat grava em
                            logs/sincronizacao_status.txt: "OK|quando|msg",
                            "ERRO|quando|msg" ou "CONFLITO|quando|msg")
POST /api/sincronizacao  -> roda scripts/sincronizar_dados.bat agora
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException

RAIZ = Path(__file__).resolve().parents[2]
ARQ_STATUS = RAIZ / "logs" / "sincronizacao_status.txt"
ARQ_LOG = RAIZ / "logs" / "sincronizacao.log"
SCRIPT = RAIZ / "scripts" / "sincronizar_dados.bat"
_rodando = threading.Lock()

router = APIRouter(prefix="/api/sincronizacao", tags=["sincronizacao"])


def ler_status(raiz: Path | None = None) -> dict[str, object]:
    base = raiz or RAIZ
    ligado = (base / ".git-dados").is_dir()
    try:
        linha = (base / "logs" / "sincronizacao_status.txt").read_text(encoding="cp1252", errors="replace").strip()
    except FileNotFoundError:
        linha = ""
    estado, quando, mensagem = (linha.split("|", 2) + ["", "", ""])[:3] if linha else ("", "", "")
    return {
        "ligado": ligado,
        "estado": estado.strip().upper(),  # OK | ERRO | CONFLITO | "" (nunca sincronizou com a versão nova)
        "quando": quando.strip(),
        "mensagem": mensagem.strip(),
        "rodando": _rodando.locked(),
    }


@router.get("")
def status() -> dict[str, object]:
    return ler_status()


@router.post("")
def sincronizar_agora() -> dict[str, object]:
    if os.name != "nt" or not SCRIPT.is_file():
        raise HTTPException(status_code=400, detail="Sincronização só roda no Windows, com o sistema instalado.")
    if not (RAIZ / ".git-dados").is_dir():
        raise HTTPException(status_code=400, detail="Este PC não está ligado ao repositório de dados.")
    if not _rodando.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Já está sincronizando.")
    try:
        subprocess.run(["cmd", "/c", str(SCRIPT)], cwd=str(RAIZ), timeout=300,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        pass
    finally:
        _rodando.release()
    return ler_status()
