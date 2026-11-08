"""
Restrições de recebimento do cliente, tiradas da observação do PDF.

Ex.: "RECEBIMENTO: Seg a quin. das 08:30h até as 11:30h ..." ou
"Horário de recebimento: Seg a Sex das 7:30 as 11:45" ou "SÓ ABRE AS 8:00".
Vira um texto curto que aparece no card e na coluna OBSERVAÇÃO DE CLIENTE
do romaneio. Só entra o trecho que fala de horário/dia.
"""

from __future__ import annotations

import re

from extrator_pdf import remover_texto_padrao

_PALAVRAS = re.compile(
    r"RECE\w{0,2}B|REC\w?EBIM|S[ÓO]\s+ABRE|ABRE\s+[ÀA]S|FECHA|HOR[ÁA]RIO|ENTREGA(R)?\s+(SOMENTE|APENAS|S[ÓO])|PORTARIA",
    re.IGNORECASE,
)
_TEM_HORA = re.compile(r"\b\d{1,2}\s*(:\s*\d{2}|h\s*\d{0,2})|\bMANH[ÃA]\b|\bTARDE\b", re.IGNORECASE)
# Texto que vem colado depois do horário e não é horário
_CORTE_FINAL = re.compile(
    r"\s*(ENVI(O|AR)\b|BOLETO|PODE\s+FATURAR|N[ÃA]O\s+EXCED|FATURAR\b|E-?MAIL)", re.IGNORECASE
)
_NAO_E_RECEBIMENTO = re.compile(r"PAGAMENTO|PGTO|BOLETO|VENCIMENTO|FATURA", re.IGNORECASE)


def extrair_restricao_recebimento(observacao: str, limite: int = 180) -> str:
    texto = remover_texto_padrao(observacao or "")
    if not texto:
        return ""
    trechos = re.split(r"\s+-\s+|\s*;\s*|(?<=[a-zà-ú\d)])\.\s+(?=[A-ZÀ-Ú])", texto)
    achados: list[str] = []
    for trecho in trechos:
        t = re.sub(r"\s+", " ", trecho).strip(" .-")
        if not t or not _PALAVRAS.search(t) or not _TEM_HORA.search(t):
            continue
        if _NAO_E_RECEBIMENTO.search(t) and not re.search(r"RECE\w{0,2}B|REC\w?EBIM", t, re.IGNORECASE):
            continue
        # "PAGAMENTO ... - RECEBIMENTO: ..." às vezes vem colado: corta no RECEB
        m = re.search(r"(RECE\w{0,2}B|REC\w?EBIM|HOR[ÁA]RIO|S[ÓO]\s+ABRE)", t, re.IGNORECASE)
        if m and m.start() > 0 and _NAO_E_RECEBIMENTO.search(t[: m.start()]):
            t = t[m.start():]
        corte = _CORTE_FINAL.search(t, 12)
        if corte:
            t = t[: corte.start()].strip(" .-")
        achados.append(t)
    resultado = " | ".join(dict.fromkeys(achados))
    return (resultado[: limite - 1] + "…") if len(resultado) > limite else resultado
