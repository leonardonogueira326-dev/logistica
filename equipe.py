"""
Motorista, ajudante e placa de cada caminhão no dia (vai para o romaneio).

A última equipe usada em cada caminhão vira sugestão para o próximo dia
(data/equipe_padrao.json); a placa vem do cadastro da frota (Mesa de Comando).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent
ARQUIVO_PADRAO = RAIZ / "data" / "equipe_padrao.json"


def frota_cadastrada() -> list[dict[str, Any]]:
    try:
        from config_operacional import carregar_configuracao

        return list(carregar_configuracao().get("frota", []))
    except Exception:  # noqa: BLE001
        return []


def carregar_padrao() -> dict[str, dict[str, str]]:
    try:
        dados = json.loads(ARQUIVO_PADRAO.read_text(encoding="utf-8"))
        return {k: v for k, v in dados.items() if isinstance(v, dict)}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def lembrar(veiculo_id: str, equipe: dict[str, str]) -> None:
    dados = carregar_padrao()
    dados[veiculo_id] = {k: str(equipe.get(k, "") or "").strip() for k in ("motorista", "ajudante")}
    ARQUIVO_PADRAO.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO_PADRAO.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def equipe_inicial() -> dict[str, dict[str, str]]:
    """Sugestão para um quadro novo: última equipe de cada caminhão + placa do cadastro."""
    padrao = carregar_padrao()
    equipe: dict[str, dict[str, str]] = {}
    for v in frota_cadastrada():
        vid = str(v.get("id", ""))
        if not vid:
            continue
        equipe[vid] = {
            "motorista": padrao.get(vid, {}).get("motorista", ""),
            "ajudante": padrao.get(vid, {}).get("ajudante", ""),
            "placa": str(v.get("placa", "") or ""),
        }
    return equipe


ARQUIVO_NOMES = RAIZ / "data" / "equipe_nomes.json"


def nomes_conhecidos() -> dict[str, list[str]]:
    """Motoristas, ajudantes e placas já usados (lista para escolher na tela)."""
    try:
        dados = json.loads(ARQUIVO_NOMES.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        dados = {}
    out = {k: [str(x) for x in dados.get(k, []) if str(x).strip()] for k in ("motoristas", "ajudantes", "placas")}
    for vid, eq in carregar_padrao().items():  # equipes antigas também entram
        for campo, lista in (("motorista", "motoristas"), ("ajudante", "ajudantes")):
            nome = str(eq.get(campo, "") or "").strip().upper()
            if nome and nome not in out[lista]:
                out[lista].append(nome)
    for v in frota_cadastrada():
        placa = str(v.get("placa", "") or "").strip().upper()
        if placa and placa not in out["placas"]:
            out["placas"].append(placa)
    return {k: sorted(v) for k, v in out.items()}


def guardar_nomes(equipe: dict[str, str]) -> None:
    dados = nomes_conhecidos()
    mudou = False
    for campo, lista in (("motorista", "motoristas"), ("ajudante", "ajudantes"), ("placa", "placas")):
        nome = str(equipe.get(campo, "") or "").strip().upper()
        if nome and nome not in dados[lista]:
            dados[lista].append(nome)
            mudou = True
    if mudou:
        ARQUIVO_NOMES.parent.mkdir(parents=True, exist_ok=True)
        ARQUIVO_NOMES.write_text(json.dumps({k: sorted(v) for k, v in dados.items()}, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
