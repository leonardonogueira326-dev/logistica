"""
Integração com LLM local (Ollama / qwen2) para classificação de observações ambíguas.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2:1.5b"
TIMEOUT_SEC = 15

STATUS_ADMINISTRATIVO = "ADMINISTRATIVO"
STATUS_VALIDOS = frozenset(
    {"RETIRA_FOB", "ENTREGA_TERCEIRO_HUB", "LIBERADO", STATUS_ADMINISTRATIVO}
)

TIPO_FRETE_POR_STATUS: dict[str, str] = {
    "RETIRA_FOB": "RETIRA_FOB",
    "ENTREGA_TERCEIRO_HUB": "ENTREGA_TERCEIRO_HUB",
    "LIBERADO": "ENTREGA_DIRETA",
    STATUS_ADMINISTRATIVO: "ENTREGA_DIRETA",
}


def _montar_prompt(texto_observacao: str, contexto_logistico: str) -> str:
    ctx = f"\nContexto: {contexto_logistico}" if contexto_logistico.strip() else ""
    return (
        "Você é um assistente logístico. Classifique a observação abaixo. "
        "Se a observação for puramente administrativa (pagamento, boletos, horários de entrega, "
        "avisos de cobrança) e não contiver instrução de transporte, responda exatamente "
        "'ADMINISTRATIVO'. Caso contrário, classifique como 'RETIRA_FOB', "
        "'ENTREGA_TERCEIRO_HUB' ou 'LIBERADO'. "
        f"Observação: {texto_observacao}{ctx}"
    )


def _parse_resposta_llm(texto: str) -> str | None:
    limpo = texto.strip().upper().replace(" ", "_")
    if STATUS_ADMINISTRATIVO in limpo or "ADMINISTRATIV" in limpo:
        return STATUS_ADMINISTRATIVO
    for status in STATUS_VALIDOS:
        if status == STATUS_ADMINISTRATIVO:
            continue
        if status in limpo or status.replace("_", " ") in texto.upper():
            return status
    if re.search(r"\bRETIRA\b|\bFOB\b|\bCOLETA\b", limpo):
        return "RETIRA_FOB"
    if re.search(r"TERCEIRO|REDESPACHO|HUB", limpo):
        return "ENTREGA_TERCEIRO_HUB"
    if re.search(r"\bLIBERADO\b", limpo):
        return "LIBERADO"
    return None


def classificar_observacao_llm(
    texto_observacao: str,
    contexto_logistico: str = "",
) -> str | None:
    """
    Classifica observação via LLM local.

    Retorna status sugerido, ADMINISTRATIVO, ou None se indisponível/timeout.
    """
    texto = (texto_observacao or "").strip()
    if not texto:
        return None

    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "prompt": _montar_prompt(texto, contexto_logistico),
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 24},
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return _parse_resposta_llm(body.get("response", ""))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    except Exception:
        return None


def tipo_frete_da_sugestao(status_llm: str) -> str | None:
    """Converte status LLM para tipo_frete interno."""
    return TIPO_FRETE_POR_STATUS.get(status_llm)
