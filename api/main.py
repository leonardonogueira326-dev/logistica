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


@app.get("/api/health", response_model=HealthSchema, tags=["health"])
def health() -> HealthSchema:
    return HealthSchema()
