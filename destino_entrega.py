"""
Entrega em outro endereço (remessa / NF triangular).

Na observação do pedido aparece algo como:
  "EMITIR NF TRIANGULAR E ENTREGAR NA EMPRESA FORT LAMINAÇÃO. NOME: ...
   ENDEREÇO RUA LUIZ OMETTO, 205 - DISTR. INDL. I - SANTA BARBARA D'OESTE"

O destino físico passa a ser essa empresa (o cliente do pedido continua o mesmo).
1º procura a empresa na base de clientes (pelo nome); 2º usa o endereço escrito
na observação. Sem nada disso, não mexe.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

_STOP = {
    "A", "O", "DA", "DE", "DO", "DAS", "DOS", "E", "EMPRESA", "CLIENTE", "LTDA", "ME", "EPP", "SA",
    "S", "EIRELI", "INDUSTRIA", "COMERCIO", "IND", "COM",
}

_RE_ENTREGAR = re.compile(
    r"ENTREGAR\s+(?:O\s+MATERIAL\s+)?(?:NA|NO|EM|PARA)\s+(?:A\s+|O\s+)?(?:EMPRESA\s+|CLIENTE\s+)?"
    r"(?P<nome>[A-Z0-9&][A-Z0-9&.'\- ]{2,60}?)"
    r"(?=\s*(?:\.|,|;|:|\s-\s|\sNOME\b|\sCNPJ\b|\sENDERECO\b|$))"
)
_RE_ENDERECO = re.compile(r"ENDERECO\s*:?\s*-?\s*(?P<end>.+?)\s*(?:$|\sCNPJ\b|\sI\.?E\.?\b|\sFONE\b|\sTEL\b)")
_RE_TRIANGULAR = re.compile(r"\bTRIA?N?GULAR\b")


def _plano(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem.upper()).strip()


def _tokens(nome: str) -> list[str]:
    return [t for t in re.findall(r"[A-Z0-9]+", _plano(nome)) if t not in _STOP and len(t) > 1]


def _do_endereco(obs: str) -> dict[str, str]:
    m = _RE_ENDERECO.search(obs)
    if not m:
        return {}
    partes = [p.strip(" .,") for p in m.group("end").split(" - ") if p.strip(" .,")]
    if len(partes) < 2:
        return {}
    return {
        "endereco": partes[0],
        "bairro": partes[1] if len(partes) >= 3 else "",
        "cidade": partes[-1],
    }


def _na_base(nome: str, base: dict[str, dict[str, Any]] | None, todos: bool = False) -> dict[str, Any] | None:
    chave = _tokens(nome) if todos else _tokens(nome)[:2]
    if not chave or not base:
        return None
    achados = [
        reg for reg in base.values()
        if all(t in _tokens(str(reg.get("razao_social") or reg.get("nome") or "")) for t in chave)
        or (len(chave) == 1 and chave[0] == _plano(str(reg.get("nome_fantasia") or "")))
    ]
    return achados[0] if len(achados) == 1 else None


def detectar_entrega(observacao: str, base: dict[str, dict[str, Any]] | None = None) -> dict[str, str] | None:
    """
    Devolve {nome, cidade, bairro, cep, codigo, triangular, origem} ou None.
    origem: "base" (achou a empresa na base de clientes) ou "observacao".
    """
    obs = _plano(observacao)
    m = _RE_ENTREGAR.search(obs)
    if not m:
        return None
    nome = m.group("nome").strip(" .-")
    if not _tokens(nome):
        return None
    triangular = "SIM" if _RE_TRIANGULAR.search(obs) else "NAO"
    reg = _na_base(nome, base)
    if reg:
        return {
            "nome": nome,
            "cidade": _plano(str(reg.get("cidade") or "")),
            "bairro": _plano(str(reg.get("bairro") or "")),
            "cep": str(reg.get("cep") or ""),
            "codigo": str(reg.get("codigo") or ""),
            "triangular": triangular,
            "origem": "base",
        }
    end = _do_endereco(obs)
    if end.get("cidade"):
        return {
            "nome": nome,
            "cidade": end["cidade"],
            "bairro": end.get("bairro", ""),
            "cep": "",
            "codigo": "",
            "triangular": triangular,
            "origem": "observacao",
        }
    return None


def rotulo(destino: dict[str, str]) -> str:
    tri = " · NF triangular" if destino.get("triangular") == "SIM" else ""
    return f"{destino['nome']} — {destino['cidade']}{tri}"


# --------------------------------------------------------------- remessa por item
# "ITEM 1 a 4 e 6 a 9 remessa LAP para mao de obra ... - ITEM 5 remessa FORT para ..."
_RE_REMESSA_ITEM = re.compile(
    r"\b(?:I?TE(?:M|NS)|TENS)\s+(?P<itens>\d+(?:\s*(?:A|ATE|-|,|E)?\s*\d+)*)\s+(?:SAO\s+|E\s+)?REMESSA\s+"
    r"(?:PARA\s+(?:A\s+)?)?(?P<nome>[A-Z0-9&][A-Z0-9&.]*(?:\s+(?!PARA\b|P/|DE\b|MAO\b)[A-Z0-9&][A-Z0-9&.]*){0,2})"
)
# Apelidos usados na observação -> como a empresa está na base de clientes
APELIDOS_REMESSA = {"FORT": "FORT LAMINACAO", "LAP": "LAMINACAO ACOS PAULINIA"}


def _itens(expr: str) -> set[int]:
    """'1 a 4 e 6 a 9' -> {1,2,3,4,6,7,8,9}; '2 3 4' -> {2,3,4}."""
    out: set[int] = set()
    for parte in re.findall(r"\d+\s*(?:A|ATE|-)\s*\d+|\d+", expr):
        m = re.match(r"(\d+)\s*(?:A|ATE|-)\s*(\d+)$", parte)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out.update(range(min(a, b), max(a, b) + 1))
        else:
            out.add(int(parte))
    return out


def detectar_remessa_por_item(
    observacao: str, numero_pedido: str, base: dict[str, dict[str, Any]] | None = None
) -> dict[str, str] | None:
    """
    Pedido 005227/26/005 + "ITEM 5 remessa FORT" -> destino FORT (procurada na base).
    Sem a empresa na base: devolve só o nome (cidade vazia) para o operador conferir.
    """
    try:
        item = int(str(numero_pedido).split("/")[-1])
    except ValueError:
        return None
    obs = re.sub(r"(?<=[A-Z])(MAO DE OBRA)", r" \1", _plano(observacao))  # "FORTmao de obra"
    for m in _RE_REMESSA_ITEM.finditer(obs):
        if item not in _itens(m.group("itens")):
            continue
        nome = m.group("nome").strip(" .")
        busca = APELIDOS_REMESSA.get(nome, nome)
        reg = _na_base(busca, base, todos=nome in APELIDOS_REMESSA)
        triangular = "SIM" if _RE_TRIANGULAR.search(obs) else "NAO"
        if reg:
            return {
                "nome": nome,
                "cidade": _plano(str(reg.get("cidade") or "")),
                "bairro": _plano(str(reg.get("bairro") or "")),
                "cep": str(reg.get("cep") or ""),
                "codigo": str(reg.get("codigo") or ""),
                "triangular": triangular,
                "origem": "base",
            }
        return {"nome": nome, "cidade": "", "bairro": "", "cep": "", "codigo": "", "triangular": triangular,
                "origem": "observacao"}
    return None


# --------------------------------------------------------------- remessa sem número de item
# "REMRESSA P/ MÃO DE OBRA NA FORT LAMINACAO - Trefilar"  (vale para todos os itens do pedido)
_RE_REMESSA_PALAVRA = re.compile(r"\bREM+R?E?S+A\b|\bINDUSTRIALIZ")
_RE_PARTES = re.compile(r"\s-\s|\.\s|;\s|\n")


def empresas_remessa() -> list[str]:
    """Apelidos das empresas que industrializam (opções da caixa de frete)."""
    return list(APELIDOS_REMESSA)


def empresa_citada(frase: str) -> str:
    """Apelido da empresa de industrialização citada na frase ('' se nenhuma)."""
    p = _plano(frase)
    for apelido, nome in APELIDOS_REMESSA.items():
        if re.search(rf"\b{re.escape(apelido)}\b", p) or nome in p:
            return apelido
    return ""


def eh_frase_de_remessa(frase: str) -> bool:
    return bool(_RE_REMESSA_PALAVRA.search(_plano(frase)))


def destino_remessa(apelido: str, base: dict[str, dict[str, Any]] | None = None) -> dict[str, str]:
    """Endereço da empresa de industrialização (pela base de clientes)."""
    nome = _plano(apelido)
    busca = APELIDOS_REMESSA.get(nome, nome)
    reg = _na_base(busca, base, todos=True)
    if reg:
        return {
            "nome": nome,
            "cidade": _plano(str(reg.get("cidade") or "")),
            "bairro": _plano(str(reg.get("bairro") or "")),
            "cep": str(reg.get("cep") or ""),
            "codigo": str(reg.get("codigo") or ""),
            "triangular": "NAO",
            "origem": "base",
        }
    return {"nome": nome, "cidade": "", "bairro": "", "cep": "", "codigo": "", "triangular": "NAO",
            "origem": "observacao"}


def detectar_remessa_geral(observacao: str, base: dict[str, dict[str, Any]] | None = None) -> dict[str, str] | None:
    """
    Remessa citada sem número de item ("REMESSA P/ MÃO DE OBRA NA FORT"): vale para o
    pedido inteiro. Se a observação separa por item ("ITEM 5 remessa FORT"), quem decide
    é detectar_remessa_por_item — aqui não mexe.
    """
    obs = _plano(observacao)
    if _RE_REMESSA_ITEM.search(obs):
        return None
    for parte in _RE_PARTES.split(obs):
        if eh_frase_de_remessa(parte):
            apelido = empresa_citada(parte)
            if apelido:
                return destino_remessa(apelido, base)
    return None
