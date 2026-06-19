"""API de configuração operacional — GET/POST /api/config."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import ConfigResponseSchema  # noqa: E402
from config_operacional import (  # noqa: E402
    ARQUIVO_CONFIG,
    carregar_configuracao,
    salvar_configuracao_validada,
)

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=ConfigResponseSchema)
def obter_config() -> ConfigResponseSchema:
    cfg = carregar_configuracao(recarregar=True)
    return ConfigResponseSchema(
        config=cfg,
        arquivo=str(ARQUIVO_CONFIG),
        message="Configuração carregada.",
    )


@router.post("", response_model=ConfigResponseSchema)
def salvar_config(body: dict[str, Any]) -> ConfigResponseSchema:
    try:
        path = salvar_configuracao_validada(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    cfg = carregar_configuracao(recarregar=True)
    return ConfigResponseSchema(
        config=cfg,
        arquivo=path,
        message="Configuração Atualizada com Sucesso",
    )
