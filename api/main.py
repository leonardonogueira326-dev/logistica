"""FastAPI — orquestrador Superfine Logística (Fase 3)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.routers.sessions import router as sessions_router  # noqa: E402
from api.routers.config import router as config_router  # noqa: E402
from api.routers.setup import router as setup_router  # noqa: E402
from api.routers.historico import router as historico_router  # noqa: E402
from api.routers.pedidos_manuais import router as pedidos_manuais_router  # noqa: E402
from api.schemas import HealthSchema  # noqa: E402
from config_operacional import carregar_configuracao  # noqa: E402

app = FastAPI(
    title="Superfine Logística API",
    version="4.0.0-fase4",
    description="Orquestra ingestão, validação, roteirização e configuração operacional.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(config_router)
app.include_router(setup_router)
app.include_router(historico_router)
app.include_router(pedidos_manuais_router)


@app.on_event("startup")
def _init_configuracao() -> None:
    carregar_configuracao()


@app.get("/api/ia/status", tags=["health"])
def ia_status() -> dict:
    from api.llm_local import status_ia

    return status_ia()


def _commit_no_disco() -> str:
    """Commit do código que está na pasta agora (lê .git sem precisar do git instalado)."""
    git = PROJECT_ROOT / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            arquivo = git / ref
            if arquivo.exists():
                return arquivo.read_text(encoding="utf-8").strip()[:7]
            for linha in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
                if linha.endswith(ref):
                    return linha[:7]
            return ""
        return head[:7]
    except OSError:
        return ""


_COMMIT_RODANDO = _commit_no_disco()


@app.get("/api/versao", tags=["health"])
def versao() -> dict:
    """Se o código na pasta mudou depois que o servidor subiu, ele está desatualizado."""
    no_disco = _commit_no_disco()
    return {
        "rodando": _COMMIT_RODANDO,
        "no_disco": no_disco,
        "desatualizado": bool(_COMMIT_RODANDO and no_disco and no_disco != _COMMIT_RODANDO),
    }


@app.get("/api/health", response_model=HealthSchema, tags=["health"])
def health() -> HealthSchema:
    return HealthSchema()


# --------------------------------------------------------------- modo servidor
# Se o frontend foi compilado (npm run build), o próprio FastAPI serve as telas:
# um processo, uma porta (http://SERVIDOR:8000), sem Node rodando em produção.
_FRONT = PROJECT_ROOT / "route-genius-main" / "dist" / "client"
_SHELL = _FRONT / "_shell.html"
# No Windows, o Python lê os tipos de arquivo do registro, que muitas vezes
# diz que .js é "text/plain". O navegador então recusa os scripts e a tela
# fica em branco. Fixamos os tipos aqui.
import mimetypes as _mimetypes

for _ext, _tipo in {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".woff2": "font/woff2",
    ".html": "text/html",
}.items():
    _mimetypes.add_type(_tipo, _ext)

if _SHELL.exists():
    from fastapi import HTTPException as _HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=_FRONT / "assets"), name="assets")

    @app.get("/{caminho:path}", include_in_schema=False)
    def _spa(caminho: str):
        if caminho.startswith("api/"):
            raise _HTTPException(status_code=404)
        arquivo = (_FRONT / caminho).resolve()
        if caminho and arquivo.is_file() and _FRONT.resolve() in arquivo.parents:
            return FileResponse(arquivo)
        return FileResponse(_SHELL)
