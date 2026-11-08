"""
Gatilhos automáticos de Quarentena — revisão obrigatória pelo operador.
"""

from __future__ import annotations

import re
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


# Pegadinhas comerciais: não mudam o frete, mas o pedido NÃO pode seguir
# sem alguém olhar. Cada item: (regex sobre texto sem acento/minúsculo, motivo).
ALERTAS_COMERCIAIS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(pagamento|pagto\.?|pgto\.?)\s+antecipad"),
        "Pagamento antecipado — aguardar liberação do comercial",
    ),
    (
        re.compile(
            r"nao\s+faturar\s+(e\s+embarcar\s+)?antes"
            r"|faturad[oa]s?\s+a\s+partir\s+de"
            r"|so\s+podemos\s+faturar"
            r"|obedecer\s+datas?"
        ),
        "Restrição de data de faturamento",
    ),
    (
        re.compile(r"nao\s+(enviar|mandar)\s+parcial|faturar\s+(sempre\s+)?total"),
        "Não aceita entrega parcial",
    ),
    (
        re.compile(r"autoriza\w*\s+(do\s+)?comercial"),
        "Exige autorização do comercial",
    ),
    (
        re.compile(
            r"nao\s+(aceita\w*|recebe\w*)\s+(\w+\s+){0,4}(emitid\w*|faturad\w*)\s+(\w+\s+){0,3}(apos|final|no\s+final|em\s+um\s+mes)"
        ),
        "Restrição de NF no fim do mês",
    ),
)


def detectar_alertas_comerciais(observacao: str, descricao: str = "") -> list[str]:
    """Retorna os motivos de alerta comercial encontrados na observação."""
    texto = _sem_acentos(f"{observacao} {descricao}").lower()
    texto = re.sub(r"\s+", " ", texto)
    return [motivo for regex, motivo in ALERTAS_COMERCIAIS if regex.search(texto)]


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

    motivos.extend(detectar_alertas_comerciais(observacao, descricao))

    if not motivos:
        return "NAO", "", palavra_chave

    return config.COD_REVISAO_OBRIGATORIA, " | ".join(motivos), palavra_chave
