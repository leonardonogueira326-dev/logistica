"""
Conferência de retira / coleta.

A logística não leva esses itens, mas confere se o sistema leu certo. Para cada
linha dizemos POR QUE ela virou retira/coleta:

- VERDE: a observação diz (COLETA, RETIRA, BUSCA...), regra aprendida, a
  "transportadora" do PDF é o próprio cliente retirando, ou o operador já
  conferiu esse cliente com essa transportadora antes;
- VERMELHO: nada disso — só a transportadora do PDF é de fora. Pode ser
  "levar na transportadora" que ninguém escreveu.

Conferir um VERMELHO grava cliente+transportadora: da próxima vez vem VERDE.
"""
from __future__ import annotations

import json
import armazenamento
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from extrator_pdf import REGEX_RETIRA_FOB, remover_texto_padrao
from normalizador import normalizar_codigo_cliente, normalizar_texto

STATUS_CONFERIR = {"RETIRA FOB", "TERCEIRO"}
ARQUIVO = Path(__file__).resolve().parent / "data" / "conferencia_frete.json"
_RE_FRASE = re.compile(r"COLETA|COLETAR|RETIRA|RETIRAR|BUSCA|BUSCAR|\bFOB\b", re.IGNORECASE)


def _get(c: Any, campo: str) -> str:
    v = c.get(campo, "") if isinstance(c, dict) else getattr(c, campo, "")
    return str(v or "")


def _chave(c: Any) -> str:
    cli = normalizar_codigo_cliente(_get(c, "cliente_codigo"))
    tr = normalizar_codigo_cliente(_get(c, "transportadora_codigo")) or normalizar_texto(_get(c, "transportadora"))[:30]
    return f"{cli}|{tr}" if cli and tr else ""


def carregar_memoria(caminho: Path = ARQUIVO) -> dict[str, dict[str, str]]:
    try:
        return armazenamento.ler(caminho)
    except Exception:
        return {}


def lembrar(linhas: list[Any], caminho: Path = ARQUIVO) -> int:
    """Grava cliente+transportadora das linhas conferidas (só as que ainda não estavam)."""
    memoria = carregar_memoria(caminho)
    novos = 0
    for c in linhas:
        k = _chave(c)
        if k and k not in memoria:
            memoria[k] = {"status": _get(c, "status"), "em": datetime.now().strftime("%d/%m/%Y")}
            novos += 1
    if novos:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        armazenamento.gravar(caminho, memoria)
    return novos


_SEPARADORES = re.compile(r"\s[-/]\s|\.\s|;\s")


def _trecho(texto: str, inicio: int, fim: int) -> str:
    """A frase da observação onde a palavra apareceu (entre separadores)."""
    antes = [m.end() for m in _SEPARADORES.finditer(texto, 0, inicio)]
    depois = _SEPARADORES.search(texto, fim)
    trecho = texto[(antes[-1] if antes else 0): (depois.start() if depois else len(texto))].strip(" -/.")
    return trecho[:70] + ("…" if len(trecho) > 70 else "")


def evidencia(c: Any, memoria: dict[str, dict[str, str]] | None = None) -> tuple[str, str]:
    """(texto, nível VERDE|VERMELHO) — vazio para quem não é retira/coleta."""
    if _get(c, "status") not in STATUS_CONFERIR:
        return "", ""
    obs = normalizar_texto(remover_texto_padrao(_get(c, "observacao_comercial")))
    m = REGEX_RETIRA_FOB.search(obs) or _RE_FRASE.search(obs)
    if m:
        return f"Observação diz: {_trecho(obs, m.start(), m.end())}", "VERDE"
    if re.search(r"\bRETIRA\b|CLIENTE\s+BUSCA", normalizar_texto(_get(c, "transportadora"))):
        return "Transportadora do PDF é o próprio cliente retirando", "VERDE"
    if _get(c, "aprendizado_aplicado") == "SIM":
        return "Regra aprendida (você já corrigiu esse caso antes)", "VERDE"
    if _get(c, "sugestao_llm_status") and "LLM" in _get(c, "auditoria").upper():
        return "A IA local leu a observação e decidiu sozinha — confira com atenção", "VERMELHO"
    lembrado = (memoria if memoria is not None else carregar_memoria()).get(_chave(c))
    if lembrado:
        return f"Já conferido antes ({lembrado.get('em', '')}): esse cliente com essa transportadora", "VERDE"
    transp = normalizar_texto(_get(c, "transportadora")).split(" - ")[0][:40] or "não informada"
    return f"Observação não fala de coleta/retirada — só a transportadora ({transp}) é de fora", "VERMELHO"
