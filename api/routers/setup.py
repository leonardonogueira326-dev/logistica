"""Endpoints de configuração operacional — Single Source of Truth."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import SetupResponseSchema  # noqa: E402
from config_operacional import (  # noqa: E402
    ARQUIVO_CONFIG,
    carregar_configuracao,
    salvar_configuracao_validada,
)

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("", response_model=SetupResponseSchema)
def obter_setup() -> SetupResponseSchema:
    cfg = carregar_configuracao(recarregar=True)
    return SetupResponseSchema(config=cfg, arquivo=str(ARQUIVO_CONFIG))


@router.put("", response_model=SetupResponseSchema)
def salvar_setup(body: dict[str, Any]) -> SetupResponseSchema:
    try:
        path = salvar_configuracao_validada(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cfg = carregar_configuracao(recarregar=True)
    return SetupResponseSchema(config=cfg, arquivo=path)
