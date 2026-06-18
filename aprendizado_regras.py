"""
Motor de aprendizado local — memória heurística em aprendizado_regras.json.

Estrutura estrita: dict plano { "codigo_palavrachave": "status_ensinado" }.
Sem listas aninhadas — compatível com persistência futura.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

import config
from normalizador import normalizar_codigo_cliente

PROJECT_ROOT = Path(__file__).resolve().parent
ARQUIVO_APRENDIZADO = PROJECT_ROOT / "data" / "aprendizado_regras.json"

STATUS_PARA_TIPO_FRETE: dict[str, str] = {
    config.COD_LIBERADO: "ENTREGA_DIRETA",
    "ENTREGA_DIRETA": "ENTREGA_DIRETA",
    config.COD_RETIRA_FOB: "RETIRA_FOB",
    "RETIRA_FOB": "RETIRA_FOB",
    config.COD_TERCEIRO_HUB: "ENTREGA_TERCEIRO_HUB",
    config.COD_TERCEIRO: "ENTREGA_TERCEIRO",
    config.COD_BLOQUEIO_FISCAL: "",
}

_cache_regras: dict[str, str] | None = None


def _sem_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_palavra_chave(palavra: str) -> str:
    """Palavra-chave para chave JSON: minúscula, sem acentos, só alfanumérico."""
    texto = _sem_acentos(str(palavra or "").strip().lower())
    return re.sub(r"[^a-z0-9]+", "", texto)


def montar_chave_regra(codigo_cliente: str, palavra_chave: str) -> str:
    codigo = normalizar_codigo_cliente(codigo_cliente)
    palavra = normalizar_palavra_chave(palavra_chave)
    if not codigo or not palavra:
        return ""
    return f"{codigo}_{palavra}"


def carregar_regras(recarregar: bool = False) -> dict[str, str]:
    """Carrega regras aprendidas (cache em memória)."""
    global _cache_regras
    if _cache_regras is not None and not recarregar:
        return _cache_regras

    regras: dict[str, str] = {}
    try:
        if ARQUIVO_APRENDIZADO.exists():
            bruto = json.loads(ARQUIVO_APRENDIZADO.read_text(encoding="utf-8"))
            if isinstance(bruto, dict):
                for chave, valor in bruto.items():
                    if str(chave).startswith("_"):
                        continue
                    if isinstance(valor, str):
                        regras[str(chave)] = valor
    except Exception:
        regras = {}

    _cache_regras = regras
    return regras


def salvar_regras(regras: dict[str, str]) -> int:
    """Persiste dict plano; retorna quantidade de regras salvas."""
    global _cache_regras
    ARQUIVO_APRENDIZADO.parent.mkdir(parents=True, exist_ok=True)

    existentes = carregar_regras()
    merged = {**existentes}
    novas = 0
    for chave, valor in regras.items():
        if chave.startswith("_") or not isinstance(valor, str):
            continue
        merged[chave] = valor
        novas += 1

    payload = {
        "_versao": "1",
        "_descricao": "Chave codigo_palavrachave -> status frete ensinado pelo operador",
        **merged,
    }
    ARQUIVO_APRENDIZADO.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _cache_regras = merged
    return novas


def registrar_regra(codigo_cliente: str, palavra_chave: str, status: str) -> str:
    """Grava uma regra; retorna a chave ou string vazia se inválida."""
    chave = montar_chave_regra(codigo_cliente, palavra_chave)
    if not chave or not status:
        return ""
    salvar_regras({chave: status.strip()})
    return chave


def _texto_para_busca(observacao: str, descricao: str) -> str:
    return _sem_acentos(f"{observacao} {descricao}").lower()


def _palavra_presente(palavra_chave: str, texto: str) -> bool:
    palavra = normalizar_palavra_chave(palavra_chave)
    if not palavra:
        return False
    texto_limpo = re.sub(r"[^a-z0-9]+", " ", texto)
    return palavra in texto_limpo.replace(" ", "") or palavra in texto_limpo.split()


def consultar_aprendizado(
    codigo_cliente: str,
    observacao: str,
    descricao: str,
    regras: Optional[dict[str, str]] = None,
) -> tuple[str, str, str] | None:
    """
    Busca regra aprendida para cliente + palavra no texto.
    Retorna (status, tipo_frete, palavra_chave) ou None.
    """
    codigo = normalizar_codigo_cliente(codigo_cliente)
    if not codigo:
        return None

    regras = regras if regras is not None else carregar_regras()
    texto = _texto_para_busca(observacao, descricao)
    prefixo = f"{codigo}_"

    candidatos: list[tuple[int, str, str]] = []
    for chave, status in regras.items():
        if not chave.startswith(prefixo):
            continue
        palavra = chave[len(prefixo) :]
        if _palavra_presente(palavra, texto):
            tipo = STATUS_PARA_TIPO_FRETE.get(status.strip(), status.strip())
            candidatos.append((len(palavra), palavra, status.strip(), tipo))

    if not candidatos:
        return None

    candidatos.sort(key=lambda x: x[0], reverse=True)
    _, palavra, status, tipo = candidatos[0]
    return status, tipo, palavra


def status_para_tipo_frete(status: str) -> str:
    return STATUS_PARA_TIPO_FRETE.get(status.strip(), status.strip())
