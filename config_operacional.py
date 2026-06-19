"""
Gestão da configuração operacional — Single Source of Truth.

Arquivo: data/configuracao_operacional.json
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import config
from param_manager import _seed_params

PROJECT_ROOT = Path(__file__).resolve().parent
ARQUIVO_CONFIG = PROJECT_ROOT / "data" / "configuracao_operacional.json"

_cache_config: dict[str, Any] | None = None


def _frota_de_params(params: dict[str, Any]) -> list[dict[str, Any]]:
    veiculos = params.get("veiculos", {})
    frota: list[dict[str, Any]] = []
    for vid, v in veiculos.items():
        frota.append(
            {
                "id": vid,
                "placa": v.get("placa", ""),
                "nome": v.get("nome", vid),
                "capacidade_kg": float(v.get("capacidade_peso", 0)),
                "tipo": v.get("tipo", "BAU"),
                "ativo": bool(v.get("disponivel", False)),
                "reserva": bool(v.get("reserva", False)),
            }
        )
    return frota


def _rotas_de_params(params: dict[str, Any]) -> list[dict[str, Any]]:
    mapeamento = params.get("mapeamento_cidades_rotas", {})
    tempos = params.get("tempos_viagem_rota_min", {})
    macro = config.REGIAO_MACRO_MAP
    rotas: list[dict[str, Any]] = []
    for cidade, rota in mapeamento.items():
        rotas.append(
            {
                "cidade": cidade,
                "rota_logistica": rota,
                "macro_regiao": macro.get(cidade, "OUTROS"),
                "tempo_medio_viagem_min": int(tempos.get(rota, 300)),
            }
        )
    return rotas


def _seed_configuracao() -> dict[str, Any]:
    params = _seed_params()
    return {
        "_versao": "1",
        "_descricao": "Single Source of Truth — frota, equipe, rotas e horários",
        "frota": _frota_de_params(params),
        "equipe": {
            "motoristas": [],
            "ajudantes": [],
        },
        "rotas": _rotas_de_params(params),
        "horarios": {
            "inicio_expediente": config.HORARIO_IN_EXPEDIENTE,
            "limite_retorno": config.HORARIO_LIMITE_RETORNO,
            "tempo_descarga_minutos": int(params.get("tempo_descarga_minutos", 20)),
            "tempo_almoco_minutos": int(params.get("tempo_almoco_minutos", 60)),
            "jornada_maxima_minutos": int(params.get("jornada_maxima_minutos", 600)),
            "velocidade_media_kmh": int(config.VELOCIDADE_MEDIA_KMH),
            "turnos": [
                {"nome": "Expediente", "saida": "07:00", "fim": "17:00"},
            ],
        },
        "operacao": {
            "peso_max_spyder_no_bau_kg": float(params.get("peso_max_spyder_no_bau_kg", 800)),
            "permitir_spyder_no_bau": config.PERMITIR_SPYDER_NO_BAU,
            "comprimentos_longos_mm": params.get("comprimentos_longos_mm", "4800, 5900"),
            "rotas_vizinhas": params.get("rotas_vizinhas", {}),
            "motivos_backlog": params.get("motivos_backlog", ""),
            "cadastro_clientes_path": params.get("cadastro_clientes_path", config.ARQUIVO_CADASTRO_XLSX),
        },
    }


def carregar_configuracao(recarregar: bool = False) -> dict[str, Any]:
    global _cache_config
    if _cache_config is not None and not recarregar:
        return deepcopy(_cache_config)

    ARQUIVO_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if ARQUIVO_CONFIG.exists():
        try:
            bruto = json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
            if isinstance(bruto, dict):
                _cache_config = bruto
                return deepcopy(_cache_config)
        except Exception:
            pass

    cfg = _seed_configuracao()
    salvar_configuracao(cfg)
    _cache_config = cfg
    return deepcopy(_cache_config)


def salvar_configuracao(cfg: dict[str, Any]) -> str:
    global _cache_config
    ARQUIVO_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    payload = deepcopy(cfg)
    payload.setdefault("_versao", "1")
    ARQUIVO_CONFIG.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _cache_config = payload
    return str(ARQUIVO_CONFIG)


def validar_configuracao(cfg: dict[str, Any]) -> list[str]:
    """Valida estrutura mínima: Frota, Equipe, Rotas e Calendário (horarios)."""
    erros: list[str] = []
    if not isinstance(cfg, dict):
        return ["O payload deve ser um objeto JSON."]

    for secao in ("frota", "equipe", "rotas", "horarios"):
        if secao not in cfg:
            erros.append(f"Seção obrigatória ausente: {secao}")

    frota = cfg.get("frota")
    if frota is not None:
        if not isinstance(frota, list):
            erros.append("frota deve ser uma lista.")
        else:
            ids_vistos: set[str] = set()
            for i, item in enumerate(frota):
                if not isinstance(item, dict):
                    erros.append(f"frota[{i}] deve ser um objeto.")
                    continue
                vid = str(item.get("id", "")).strip()
                if not vid:
                    erros.append(f"frota[{i}]: campo id é obrigatório.")
                elif vid in ids_vistos:
                    erros.append(f"frota: id duplicado '{vid}'.")
                else:
                    ids_vistos.add(vid)
                try:
                    cap = float(item.get("capacidade_kg", 0))
                    if cap < 0:
                        erros.append(f"frota[{i}]: capacidade_kg não pode ser negativa.")
                except (TypeError, ValueError):
                    erros.append(f"frota[{i}]: capacidade_kg inválida.")

    equipe = cfg.get("equipe")
    if equipe is not None:
        if not isinstance(equipe, dict):
            erros.append("equipe deve ser um objeto.")
        else:
            for tipo in ("motoristas", "ajudantes"):
                lista = equipe.get(tipo)
                if lista is None:
                    erros.append(f"equipe.{tipo} é obrigatório.")
                elif not isinstance(lista, list):
                    erros.append(f"equipe.{tipo} deve ser uma lista.")
                else:
                    for j, pessoa in enumerate(lista):
                        if not isinstance(pessoa, dict):
                            erros.append(f"equipe.{tipo}[{j}] deve ser um objeto.")
                            continue
                        if not str(pessoa.get("nome", "")).strip():
                            erros.append(f"equipe.{tipo}[{j}]: nome é obrigatório.")

    rotas = cfg.get("rotas")
    if rotas is not None:
        if not isinstance(rotas, list):
            erros.append("rotas deve ser uma lista.")
        else:
            for i, rota in enumerate(rotas):
                if not isinstance(rota, dict):
                    erros.append(f"rotas[{i}] deve ser um objeto.")
                    continue
                if not str(rota.get("cidade", "")).strip():
                    erros.append(f"rotas[{i}]: cidade é obrigatória.")
                if not str(rota.get("rota_logistica", "")).strip():
                    erros.append(f"rotas[{i}]: rota_logistica é obrigatória.")
                if not str(rota.get("macro_regiao", "")).strip():
                    erros.append(f"rotas[{i}]: macro_regiao é obrigatória.")
                try:
                    tempo = int(rota.get("tempo_medio_viagem_min", 0))
                    if tempo <= 0:
                        erros.append(f"rotas[{i}]: tempo_medio_viagem_min deve ser > 0.")
                except (TypeError, ValueError):
                    erros.append(f"rotas[{i}]: tempo_medio_viagem_min inválido.")

    horarios = cfg.get("horarios")
    if horarios is not None:
        if not isinstance(horarios, dict):
            erros.append("horarios deve ser um objeto (Calendário).")
        else:
            for campo in ("inicio_expediente", "limite_retorno"):
                if not str(horarios.get(campo, "")).strip():
                    erros.append(f"horarios.{campo} é obrigatório.")
            turnos = horarios.get("turnos")
            if turnos is not None and not isinstance(turnos, list):
                erros.append("horarios.turnos deve ser uma lista.")

    return erros


def salvar_configuracao_validada(cfg: dict[str, Any]) -> str:
    """Valida e persiste configuracao_operacional.json."""
    erros = validar_configuracao(cfg)
    if erros:
        raise ValueError("; ".join(erros))
    return salvar_configuracao(cfg)


def configuracao_para_parametros(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Converte configuracao_operacional.json para dict usado pelo motor_logistica."""
    cfg = cfg or carregar_configuracao()
    horarios = cfg.get("horarios", {})
    operacao = cfg.get("operacao", {})

    mapeamento: dict[str, str] = {}
    tempos: dict[str, int] = {}
    for rota in cfg.get("rotas", []):
        cidade = str(rota.get("cidade", "")).strip().upper()
        rota_id = str(rota.get("rota_logistica", "ROTA_OUTROS"))
        if cidade:
            mapeamento[cidade] = rota_id
        if rota_id not in tempos:
            tempos[rota_id] = int(rota.get("tempo_medio_viagem_min", 300))

    veiculos: dict[str, dict[str, Any]] = {}
    ordem_ids: list[str] = []
    for v in cfg.get("frota", []):
        vid = str(v.get("id", "")).strip()
        if not vid:
            continue
        ordem_ids.append(vid)
        veiculos[vid] = {
            "nome": v.get("nome", vid),
            "placa": v.get("placa", ""),
            "capacidade_peso": float(v.get("capacidade_kg", 0)),
            "tipo": v.get("tipo", "BAU"),
            "disponivel": bool(v.get("ativo", False)),
            "reserva": bool(v.get("reserva", False)),
        }

    return {
        "cadastro_clientes_path": operacao.get("cadastro_clientes_path", config.ARQUIVO_CADASTRO_XLSX),
        "mapeamento_cidades_rotas": mapeamento,
        "rotas_vizinhas": operacao.get("rotas_vizinhas", {}),
        "tempos_viagem_rota_min": tempos,
        "tempo_descarga_minutos": int(horarios.get("tempo_descarga_minutos", 20)),
        "tempo_almoco_minutos": int(horarios.get("tempo_almoco_minutos", 60)),
        "jornada_maxima_minutos": int(horarios.get("jornada_maxima_minutos", 600)),
        "inicio_expediente": horarios.get("inicio_expediente", config.HORARIO_IN_EXPEDIENTE),
        "limite_retorno": horarios.get("limite_retorno", config.HORARIO_LIMITE_RETORNO),
        "velocidade_media_kmh": int(horarios.get("velocidade_media_kmh", config.VELOCIDADE_MEDIA_KMH)),
        "peso_max_spyder_no_bau_kg": float(operacao.get("peso_max_spyder_no_bau_kg", 800)),
        "permitir_spyder_no_bau": bool(operacao.get("permitir_spyder_no_bau", True)),
        "comprimentos_longos_mm": operacao.get("comprimentos_longos_mm", "4800, 5900"),
        "motivos_backlog": operacao.get("motivos_backlog", ""),
        "veiculos": veiculos,
        "ordem_veiculos": ordem_ids,
        "equipe": cfg.get("equipe", {}),
        "turnos": horarios.get("turnos", []),
    }
