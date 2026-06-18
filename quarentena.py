"""
Gatilhos automáticos de Quarentena — revisão obrigatória pelo operador.
"""

from __future__ import annotations

import unicodedata

import config

PALAVRAS_SUSPEITAS = (
    "triangulacao",
    "triangulação",
    "remessa",
    "industrializacao",
    "industrialização",
    "fort",
    "retorno",
)


def _sem_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def detectar_palavra_suspeita(observacao: str, descricao: str = "") -> str:
    """Retorna a primeira palavra suspeita encontrada ou string vazia."""
    texto = _sem_acentos(f"{observacao} {descricao}").lower()
    for palavra in PALAVRAS_SUSPEITAS:
        chave = _sem_acentos(palavra).lower()
        if chave in texto:
            return palavra
    return ""


def avaliar_quarentena(
    peso_kg: float,
    observacao: str,
    descricao: str = "",
    aprendizado_aplicado: str = "NAO",
) -> tuple[str, str, str]:
    """
    Avalia se o pedido exige revisão obrigatória.

    Retorna (revisao_obrigatoria, motivo_quarentena, palavra_chave).
    """
    if aprendizado_aplicado == "SIM":
        return "NAO", "", ""

    motivos: list[str] = []
    palavra_chave = ""

    if peso_kg == 0.0:
        motivos.append("Peso Zerado")

    suspeita = detectar_palavra_suspeita(observacao, descricao)
    if suspeita:
        motivos.append(f"Palavra Suspeita: {suspeita}")
        palavra_chave = suspeita

    if not motivos:
        return "NAO", "", palavra_chave

    return config.COD_REVISAO_OBRIGATORIA, " | ".join(motivos), palavra_chave
