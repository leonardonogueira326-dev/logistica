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
from api.schemas import HealthSchema  # noqa: E402

app = FastAPI(
    title="Superfine Logística API",
    version="3.0.0-fase3",
    description="Orquestra ingestão, validação e roteirização.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)


@app.get("/api/health", response_model=HealthSchema, tags=["health"])
def health() -> HealthSchema:
    return HealthSchema()
