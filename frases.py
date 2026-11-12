"""
Dicionário de frases da observação.

Em vez de escrever uma regra para cada pegadinha, o sistema quebra a observação
em frases, troca o que muda de um pedido para outro (datas, números, valores,
e-mails) por coringas e compara com o que já conhece:

- CONHECIDA pelo operador (data/frases_conhecidas.json): aplica o significado
  ensinado (ignorar, mudar o frete, prazo, sempre avisar);
- CONHECIDA por regra do sistema: financeiro/fiscal sem nada de logística,
  horário de recebimento, frase de frete que as regras já entendem;
- NOVA: aparece na Conferência para o operador ensinar (com uma sugestão,
  que ele aprova ou troca). Nada é aplicado sem aprovação.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from destino_entrega import empresa_citada, empresas_remessa, eh_frase_de_remessa

ARQUIVO = Path(__file__).resolve().parent / "data" / "frases_conhecidas.json"

IGNORAR = "IGNORAR"
FRETE = "FRETE"
FATURAR_APOS = "FATURAR_APOS"
ENTREGAR_ATE = "ENTREGAR_ATE"
AVISAR = "AVISAR"
INDUSTRIALIZACAO = "INDUSTRIALIZACAO"  # status = apelido da empresa (FORT, LAP)
SIGNIFICADOS = (IGNORAR, FRETE, FATURAR_APOS, ENTREGAR_ATE, AVISAR, INDUSTRIALIZACAO)

# status do consolidado <-> tipo de frete do classificador
STATUS_PARA_TIPO = {
    "LIBERADO": "ENTREGA_DIRETA",
    "ENTREGA_TERCEIRO_HUB": "ENTREGA_TERCEIRO_HUB",
    "TERCEIRO": "ENTREGA_TERCEIRO",
    "RETIRA FOB": "RETIRA_FOB",
}

_RE_SEPARA = re.compile(r"\s[-/]\s|\.\s|;\s|\n|\*\*")
_RE_DATA = re.compile(r"\b\d{1,2}[/.]\d{1,2}(?:[/.]\d{2,4})?\b")
_RE_EMAIL = re.compile(r"\S+@\S+")
_RE_VALOR = re.compile(r"R\$\s*[\d.,]+")
_RE_NUM = re.compile(r"\b\d+(?:[.,]\d+)*\b")

# Fala com a logística: nunca é ignorada automaticamente
_RE_LOGISTICA = re.compile(
    r"ENTREG|RECEB|MERCADORIA|COLET|RETIR|TRANSP|EMBARC|CAMINH|CARREG|PARCIAL|CAIXA|PALLET|PALET|"
    r"AVISAR|LIGAR|FALAR|LOGISTIC|EXPEDI|PESO|AGENDA|DESCARGA|MOTORISTA|FERIAS|FECHAD|PORTARIA|"
    r"\bLEVAR\b|\bLEVA\b|\bBUSCA"
)
# Financeiro / fiscal / comercial
_RE_ADMIN = re.compile(
    r"BOLETO|VENC|PAGT|PAGAMENTO|PGTO|TITULO|FACTORING|PARCELA|CNPJ|\bI\.?E\b|ICMS|"
    r"NOTA DE SERVICO|FINANCEIRO|CARTEIRA|DIRETORIA|\bNFS?\b|NOTA FISCAL|NOTAS|FATURAR TOTAL|"
    r"ORDEM DE COMPRA|\bO\.?C\b|MAO DE OBRA|CREDITO|DEPOSITO|PRORROG|COBRANCA|DIAMETRO|BITOLA|"
    r"CERTIFICADO|PRECO|<EMAIL>|DECRETO|\bIPI\b|\bNCM\b|\bCFOP\b|FISCAL|ARTIGO|\bLEI\b"
)
# Pedaço de endereço / nome (vem junto com "entregar na empresa X")
_RE_ENDERECO = re.compile(r"^(?:NOME|ENDERECO|END|RUA|R|AV|AVENIDA|CEP|BAIRRO|PQ|JD|VILA|ROD|ESTRADA|P)\b")
_RE_HORARIO = re.compile(r"RECEBIMENTO|RECDEBIMENTO|HORARIO|\b\d{1,2}H|\d:\d|\bHS\b|HRS")
_RE_FATURAR_APOS = re.compile(r"A PARTIR|EM DIANTE|\bAPOS\b|ANTES D[AE]|NAO FATURAR.*(?:ANTES|DATA)")
_RE_ATE = re.compile(r"\bATE\b")


def _plano(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem.upper()).strip()


def quebrar(observacao: str) -> list[str]:
    """Frases da observação (sem o texto padrão do decreto)."""
    from extrator_pdf import remover_texto_padrao

    texto = remover_texto_padrao(observacao or "")
    frases = []
    for parte in _RE_SEPARA.split(texto):
        parte = parte.strip(" .-/*:")
        if len(chave(parte).split()) >= 3:
            frases.append(parte)
    return frases


def chave(frase: str) -> str:
    """Forma comparável: datas, e-mails, valores e números viram coringas."""
    t = _plano(frase)
    t = _RE_EMAIL.sub(" <EMAIL> ", t)
    t = _RE_VALOR.sub(" <VALOR> ", t)
    t = _RE_DATA.sub(" <DATA> ", t)
    t = _RE_NUM.sub(" <N> ", t)
    t = re.sub(r"[^A-Z<> ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def datas(frase: str) -> list[str]:
    return _RE_DATA.findall(frase or "")


def carregar(caminho: Path = ARQUIVO) -> dict[str, dict[str, Any]]:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return {}


def ensinar(
    k: str, exemplo: str, significado: str, status: str = "", caminho: Path = ARQUIVO
) -> dict[str, Any]:
    if significado not in SIGNIFICADOS:
        raise ValueError(f"Significado inválido: {significado}")
    if significado == FRETE and status not in STATUS_PARA_TIPO:
        raise ValueError("Para 'muda o frete' escolha o frete.")
    if significado == INDUSTRIALIZACAO and status not in empresas_remessa():
        raise ValueError("Para 'remessa para industrialização' escolha a empresa.")
    dic = carregar(caminho)
    dic[k] = {
        "significado": significado,
        "status": status if significado in (FRETE, INDUSTRIALIZACAO) else "",
        "exemplo": exemplo[:200],
        "em": datetime.now().strftime("%d/%m/%Y"),
    }
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dic, ensure_ascii=False, indent=2), encoding="utf-8")
    return dic[k]


def _parecida(k: str, dic: dict[str, dict[str, Any]]) -> str | None:
    """Mesma frase com uma ou outra palavra diferente (>= 85% das palavras)."""
    a = set(k.split())
    melhor, nota = None, 0.0
    for outra in dic:
        b = set(outra.split())
        if not b:
            continue
        j = len(a & b) / len(a | b)
        if j > nota:
            melhor, nota = outra, j
    return melhor if nota >= 0.85 else None


def sugestao(frase: str) -> tuple[str, str]:
    """(significado, status) mais provável — só sugestão, o operador decide."""
    from extrator_pdf import classificar_frete_com_confianca

    p = _plano(frase)
    if eh_frase_de_remessa(frase) or "MAO DE OBRA" in p:
        return INDUSTRIALIZACAO, empresa_citada(frase)
    if datas(frase):
        if _RE_FATURAR_APOS.search(p):
            return FATURAR_APOS, ""
        if _RE_ATE.search(p) and re.search(r"ENTREG|LEVAR|RECEB", p):
            return ENTREGAR_ATE, ""
    tipo, alta = classificar_frete_com_confianca(p, "", "", "")
    if alta and re.search(r"COLET|RETIR|TRANSP|BUSCA|\bLEVA", p):
        status = {v: k for k, v in STATUS_PARA_TIPO.items()}.get(tipo, "")
        if status:
            return FRETE, status
    if _RE_LOGISTICA.search(p):
        return AVISAR, ""
    return IGNORAR, ""


def analisar(observacao: str, dic: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """
    Cada frase com: texto, chave, situacao (OPERADOR | REGRA | NOVA),
    significado, status (frete), datas, sugestao.
    """
    dic = carregar() if dic is None else dic
    out: list[dict[str, Any]] = []
    for frase in quebrar(observacao):
        k = chave(frase)
        item: dict[str, Any] = {"texto": frase, "chave": k, "datas": datas(frase)}
        conhecida = dic.get(k) or (dic.get(p) if (p := _parecida(k, dic)) else None)
        if conhecida:
            item.update(situacao="OPERADOR", significado=conhecida["significado"],
                        status=conhecida.get("status", ""), ensinada_em=conhecida.get("em", ""))
        elif eh_frase_de_remessa(frase):
            # Remessa para industrialização: o sistema entende sozinho quando a empresa
            # é conhecida; senão pergunta (nunca ignora — muda para onde o material vai).
            empresa = empresa_citada(frase)
            if empresa:
                item.update(situacao="REGRA", significado=INDUSTRIALIZACAO, status=empresa)
            else:
                item.update(situacao="NOVA", significado="", status="",
                            sugestao=INDUSTRIALIZACAO, sugestao_status="")
        else:
            sig, st = sugestao(frase)
            plano = _plano(frase)
            horario = bool(_RE_HORARIO.search(plano)) and "<DATA>" not in k and bool(
                re.search(r"\d{1,2}\s*(?::|H\b|HS\b|HRS|HORAS)", plano)
            )
            automatica = (
                (_RE_ADMIN.search(k) and not _RE_LOGISTICA.search(plano))
                or horario
                or bool(_RE_ENDERECO.search(k))
                or sig == FRETE
            )
            item.update(situacao="REGRA" if automatica else "NOVA",
                        significado=(sig if sig == FRETE else "HORARIO" if horario else IGNORAR)
                        if automatica else "",
                        status=st if automatica else "",
                        sugestao=sig, sugestao_status=st)
        out.append(item)
    return out


def frete_ensinado(observacao: str, dic: dict[str, dict[str, Any]] | None = None) -> str:
    """Tipo de frete ensinado pelo operador para alguma frase da observação ('' se nenhum)."""
    for f in analisar(observacao, dic):
        if f["situacao"] == "OPERADOR" and f["significado"] == FRETE and f.get("status"):
            return STATUS_PARA_TIPO.get(f["status"], "")
    return ""


def industrializacao_ensinada(observacao: str, dic: dict[str, dict[str, Any]] | None = None) -> str:
    """Empresa de industrialização ensinada pelo operador para alguma frase ('' se nenhuma)."""
    for f in analisar(observacao, dic):
        if f["situacao"] == "OPERADOR" and f["significado"] == INDUSTRIALIZACAO and f.get("status"):
            return f["status"]
    return ""
