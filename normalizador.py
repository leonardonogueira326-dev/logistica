"""
Utilitários de normalização para o motor de ingestão Superfine.
Todas as strings de busca passam por .strip().upper().
"""

from __future__ import annotations

import re
from typing import Optional


def normalizar_texto(valor: Optional[str]) -> str:
    """Retorna string limpa em maiúsculas."""
    try:
        if valor is None:
            return ""
        return str(valor).strip().upper()
    except Exception:
        return ""


def normalizar_pedido(pedido: Optional[str]) -> str:
    """
    Padroniza pedido para NNNNNN/AA/SSS.
    Ex.: 2980/26/01 -> 002980/26/001
    """
    try:
        texto = normalizar_texto(pedido)
        if not texto:
            return ""

        match = re.match(r"^(\d+)/(\d{2})/(\d{2,3})$", texto)
        if not match:
            return texto

        numero, ano, seq = match.groups()
        return f"{int(numero):06d}/{ano}/{seq.zfill(3)}"
    except Exception:
        return normalizar_texto(pedido)


def expandir_pedidos_compostos(pedido_raw: Optional[str]) -> str:
    """
    Converte pedido composto em string CSV (sem listas).
    Ex.: 1654/26/01/02/03 -> "1654/26/01, 1654/26/02, 1654/26/03"
    """
    try:
        texto = str(pedido_raw or "").strip()
        if not texto:
            return ""

        partes = texto.split("/")
        if len(partes) <= 3:
            return normalizar_pedido(texto)

        base_num = partes[0]
        base_ano = partes[1]
        sequencias = partes[2:]

        expandidos = [
            normalizar_pedido(f"{base_num}/{base_ano}/{seq}")
            for seq in sequencias
            if seq
        ]
        return ", ".join(p for p in expandidos if p)
    except Exception:
        return normalizar_texto(pedido_raw)


def parse_peso_kg(valor: Optional[str]) -> float:
    """Converte '1.000,00' ou '50,00 KG' para float."""
    try:
        texto = str(valor or "").strip().upper().replace("KG", "").strip()
        if not texto:
            return 0.0
        texto = texto.replace(".", "").replace(",", ".")
        return float(texto)
    except Exception:
        return 0.0


def parse_moeda_br(valor: Optional[str]) -> float:
    """Converte valor monetário brasileiro para float."""
    try:
        texto = str(valor or "").strip()
        if not texto:
            return 0.0
        texto = texto.replace(".", "").replace(",", ".")
        return float(texto)
    except Exception:
        return 0.0


def normalizar_codigo_cliente(codigo: Optional[str]) -> str:
    """01351 -> 1351 para match PDF ↔ cadastro mestre."""
    try:
        texto = str(codigo or "").strip()
        if not texto:
            return ""
        if texto.isdigit():
            return str(int(texto))
        return texto
    except Exception:
        return str(codigo or "").strip()


def resolver_rota_logistica(cidade_destino: Optional[str], params: dict) -> str:
    """Resolve rota logística via De-Para de cidades."""
    try:
        cidade = normalizar_texto(cidade_destino)
        mapeamento = params.get("mapeamento_cidades_rotas", {})
        return mapeamento.get(cidade, "ROTA_OUTROS")
    except Exception:
        return "ROTA_OUTROS"


def extrair_cidade_transportadora(texto_transportadora: Optional[str]) -> str:
    """
    Extrai cidade da linha Transp: (ex.: 'GRIFE - RUA X, 24, GUARULHOS -' -> GUARULHOS).
    """
    try:
        texto = normalizar_texto(texto_transportadora)
        if not texto:
            return ""

        texto = re.sub(r"\s*-\s*$", "", texto)

        if "," in texto:
            ultimo = texto.rsplit(",", 1)[-1].strip()
            ultimo = re.sub(r"\s*-\s*$", "", ultimo)
            if ultimo and re.match(r"^[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]", ultimo) and not re.match(
                r"^\d", ultimo
            ):
                return " ".join(ultimo.split())

        segmentos = [s.strip() for s in re.split(r"\s*-\s*", texto) if s.strip()]
        if len(segmentos) >= 2:
            meio = segmentos[1]
            if re.match(r"^[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9\s'\.\(\)]+$", meio):
                if not any(
                    tok in meio
                    for tok in ("RUA", "R.", "AV ", "AV.", "ROD", "KIDA", "JARAGUA", "NUM")
                ):
                    if 1 <= len(meio.split()) <= 3:
                        return " ".join(meio.split())

        for seg in reversed(segmentos):
            if re.match(r"^\d", seg):
                continue
            if any(
                tok in seg
                for tok in ("RUA", "R.", "AV ", "AV.", "ROD", "KIDA", "JARAGUA", "NUM")
            ):
                continue
            if re.match(r"^[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9\s'\.\(\)]+$", seg):
                if 2 <= len(seg.split()) <= 5:
                    return " ".join(seg.split())

        return ""
    except Exception:
        return ""


def normalizar_cliente(cliente: Optional[str]) -> str:
    """Remove sufixos operacionais e normaliza para comparação."""
    try:
        texto = normalizar_texto(cliente)
        for sufixo in ("(CR)", "(TC)", "(AMOSTRA / SEM PAGTO)"):
            texto = texto.replace(sufixo, "")
        return " ".join(texto.split())
    except Exception:
        return normalizar_texto(cliente)


def montar_id_item(numero_pedido: str, of_ano: str = "", sequencia: str = "") -> str:
    """
    Identidade de uma linha de faturamento: pedido/ano/item + OF.

    O mesmo pedido/item pode ter várias OFs (003060/26/002 com 3 OFs) e o mesmo
    item+OF pode voltar em outro dia com o saldo da produção — por isso o número
    do pedido sozinho não identifica a linha. Sem OF, usa a sequência da
    solicitação como desempate.
    """
    pedido = (numero_pedido or "").strip()
    of = (of_ano or "").strip()
    if not pedido:
        return ""
    if of:
        return f"{pedido}#{of}"
    if sequencia:
        return f"{pedido}#SEQ{str(sequencia).strip()}"
    return pedido


def mesma_linha(obj, chave: str) -> bool:
    """
    True se `obj` (dict ou dataclass) é a linha identificada por `chave`.

    A chave preferida é o id_item (pedido/item#OF). O nº do pedido puro ainda é
    aceito por compatibilidade, mas só quando não há OF na chave.
    """
    if not chave:
        return False
    get = obj.get if isinstance(obj, dict) else (lambda k, d="": getattr(obj, k, d))
    for campo in ("id_carga", "id_item"):
        if get(campo, "") == chave:
            return True
    if "#" in chave:
        return False
    return get("numero_pedido", "") == chave or get("numero_pedido_norm", "") == chave
