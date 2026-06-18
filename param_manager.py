"""
Gerenciador de parâmetros operacionais (JSON).
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import config

_ARQUIVO_PADRAO = Path(__file__).parent / "parametros_operacionais.json"


def _seed_params() -> dict[str, Any]:
    """Parâmetros iniciais derivados de config.py quando JSON não existe."""
    veiculos = {}
    for vid, v in config.VEICULOS.items():
        veiculos[vid] = deepcopy(v)

    return {
        "cadastro_clientes_path": config.ARQUIVO_CADASTRO_XLSX,
        "mapeamento_cidades_rotas": {
            "SAO PAULO": "ROTA_CAPITAL",
            "DIADEMA": "ROTA_ABC",
            "SAO BERNARDO DO CAMPO": "ROTA_ABC",
            "SANTO ANDRE": "ROTA_ABC",
            "MAUA": "ROTA_ABC",
            "GUARULHOS": "ROTA_LESTE",
            "CAMPINAS": "ROTA_INTERIOR_RMC",
            "VALINHOS": "ROTA_INTERIOR_RMC",
            "AMERICANA": "ROTA_INTERIOR_RMC",
            "CONTAGEM": "ROTA_MG",
            "GARIBALDI": "ROTA_SUL",
        },
        "rotas_vizinhas": {
            "ROTA_CAPITAL": "ROTA_ABC, ROTA_LESTE",
            "ROTA_ABC": "ROTA_CAPITAL, ROTA_LESTE",
            "ROTA_LESTE": "ROTA_CAPITAL, ROTA_ABC",
            "ROTA_INTERIOR_RMC": "ROTA_CAPITAL",
            "ROTA_MG": "ROTA_INTERIOR_RMC",
            "ROTA_SUL": "ROTA_OUTROS",
            "ROTA_OUTROS": "",
        },
        "tempos_viagem_rota_min": {
            "ROTA_CAPITAL": 240,
            "ROTA_ABC": 210,
            "ROTA_LESTE": 210,
            "ROTA_INTERIOR_RMC": 120,
            "ROTA_MG": 300,
            "ROTA_SUL": 360,
            "ROTA_OUTROS": 300,
        },
        "tempo_descarga_minutos": config.TEMPO_DESCARGA_MINUTOS,
        "tempo_almoco_minutos": 60,
        "jornada_maxima_minutos": 600,
        "peso_max_spyder_no_bau_kg": config.PESO_MAX_SPYDER_NO_BAU,
        "comprimentos_longos_mm": "4800, 5000, 5900, 6000",
        "veiculos": veiculos,
        "motivos_backlog": (
            "FROTA INSUFICIENTE, LIMITE DE JORNADA ATINGIDO, "
            "BLOQUEIO FISCAL, TRAVADO COMERCIAL, RETIRA FOB, TERCEIRO"
        ),
    }


def carregar_parametros(caminho: str = "") -> dict[str, Any]:
    """Carrega parâmetros do JSON ou cria seed."""
    path = Path(caminho) if caminho else _ARQUIVO_PADRAO
    try:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return _seed_params()


def salvar_parametros(params: dict[str, Any], caminho: str = "") -> str:
    path = Path(caminho) if caminho else _ARQUIVO_PADRAO
    with open(path, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)
    return str(path)


def rotulo_rota(rota_logistica: str) -> str:
    return config.ROTULOS_ROTA.get(rota_logistica, rota_logistica.replace("ROTA_", ""))
