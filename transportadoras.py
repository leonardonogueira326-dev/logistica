"""
Endereço da transportadora (linhas "Levar na transportadora" / ENTREGA_TERCEIRO_HUB).

Ordem de confiança:
  1. base-transportadoras.xlsx (aba Dados) com as colunas de endereço preenchidas
     — ENDERECO, NUMERO, BAIRRO, CIDADE, UF, CEP, HORARIO_RECEBIMENTO, OBS;
  2. endereço que veio no PDF depois do nome ("RODOVIASUL - RUA X, 105, SAO PAULO - 02178-040"),
     só quando traz a cidade;
  3. nada: a linha avisa "transportadora sem endereço — cadastre".
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from normalizador import normalizar_codigo_cliente, normalizar_texto, resolver_rota_logistica

RAIZ = Path(__file__).resolve().parent
NOMES_BASE = ("base-transportadoras.xlsx",)

# cabeçalho (sem acento, maiúsculo) -> campo
_COLUNAS = {
    "CODIGO": "codigo", "COD": "codigo",
    "NOME_FANTASIA": "nome", "FANTASIA": "nome",
    "RAZAO_SOCIAL": "razao_social",
    "TELEFONE": "telefone", "FONE": "telefone",
    "ENDERECO": "endereco", "LOGRADOURO": "endereco", "RUA": "endereco",
    "NUMERO": "numero", "NO": "numero", "N": "numero", "NRO": "numero",
    "BAIRRO": "bairro",
    "CIDADE": "cidade", "MUNICIPIO": "cidade",
    "UF": "uf", "ESTADO": "uf",
    "CEP": "cep",
    "HORARIO_RECEBIMENTO": "horario", "HORARIO": "horario", "HORARIO_DE_RECEBIMENTO": "horario",
    "OBS": "obs", "OBSERVACAO": "obs", "OBSERVACOES": "obs",
}
_RUA = re.compile(r"^(R\.?|RUA|AV\.?|AVENIDA|ROD\.?|RODOVIA|ESTR\.?|ESTRADA|AL\.?|ALAMEDA|TRAV\.?|PCA|PRACA|VIA|KM)\b")
_CEP = re.compile(r"\b(\d{5})-?(\d{3})\b")

_cache: dict[str, Any] = {}


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def _cab(valor: Any) -> str:
    t = _sem_acento(normalizar_texto(str(valor or "")))
    return re.sub(r"[^A-Z0-9]+", "_", t).strip("_")


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return " ".join(str(valor).split())


def carregar(pasta: Path | str | None = None) -> dict[str, dict[str, str]]:
    """codigo (sem zeros à esquerda) -> dados da transportadora."""
    raiz = Path(pasta) if pasta else RAIZ
    candidatos = [raiz / n for n in NOMES_BASE if (raiz / n).is_file()]
    if not candidatos:
        return {}
    caminho = candidatos[0]
    marca = (str(caminho), caminho.stat().st_mtime)
    if _cache.get("marca") == marca:
        return _cache["dados"]
    import openpyxl

    dados: dict[str, dict[str, str]] = {}
    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        ws = wb["Dados"] if "Dados" in wb.sheetnames else wb.worksheets[0]
        linhas = ws.iter_rows(values_only=True)
        idx: dict[str, int] = {}
        for i, c in enumerate(next(linhas, []) or []):
            campo = _COLUNAS.get(_cab(c))
            if campo and campo not in idx:
                idx[campo] = i
        if "codigo" not in idx:
            return {}
        for linha in linhas:
            reg = {campo: _texto(linha[i]) if i < len(linha) else "" for campo, i in idx.items()}
            codigo = normalizar_codigo_cliente(reg.get("codigo", ""))
            if codigo:
                reg["codigo"] = codigo
                dados[codigo] = reg
    finally:
        wb.close()
    _cache.update(marca=marca, dados=dados)
    return dados


def endereco_do_pdf(texto: str) -> dict[str, str]:
    """
    'RODOVIASUL - RUA SOLDADO JOSE REYMAO, 105, SAO PAULO - 02178-040 - (11)2412-7843'
      -> {nome: RODOVIASUL, endereco: RUA SOLDADO JOSE REYMAO, 105, cidade: SAO PAULO, cep: 02178-040}
    Cortado ('L B LOG - R. HEROI DA FORCA EXPED. BRASILEIRA,') -> sem cidade.
    """
    t = normalizar_texto(texto or "")
    if not t:
        return {}
    nome, _, resto = t.partition(" - ")
    out = {"nome": nome.strip(), "endereco": "", "cidade": "", "cep": ""}
    m = _CEP.search(resto)
    if m:
        out["cep"] = f"{m.group(1)}-{m.group(2)}"
    rua_cidade = re.split(r"\s+-\s+(?=[\d(])|\s+-\s*$", resto)[0].strip(" ,-")
    partes = [p.strip() for p in rua_cidade.split(",") if p.strip()]
    # rua, número, cidade  — a cidade é o último pedaço que não é rua nem número
    if len(partes) >= 2:
        ultimo = partes[-1]
        if not _RUA.match(ultimo) and not re.match(r"^\d", ultimo) and ultimo != out["nome"]:
            out["cidade"] = ultimo
            out["endereco"] = ", ".join(partes[:-1])
        else:
            out["endereco"] = ", ".join(partes)
    elif partes:
        out["endereco"] = partes[0]
    return out


def endereco_transportadora(
    codigo: str, texto_pdf: str = "", base: dict[str, dict[str, str]] | None = None
) -> dict[str, str]:
    """Melhor endereço conhecido. 'origem' = base | pdf | '' (sem endereço)."""
    base = carregar() if base is None else base
    cod = normalizar_codigo_cliente(codigo or "")
    reg = base.get(cod, {}) if cod else {}
    pdf = endereco_do_pdf(texto_pdf)
    nome = reg.get("nome") or pdf.get("nome") or normalizar_texto(texto_pdf).split(" - ")[0]
    if reg.get("cidade"):
        rua = reg.get("endereco", "")
        if reg.get("numero") and rua:
            rua = f"{rua}, {reg['numero']}"
        return {
            "codigo": cod, "nome": nome, "endereco": normalizar_texto(rua), "bairro": normalizar_texto(reg.get("bairro", "")),
            "cidade": normalizar_texto(reg["cidade"]), "uf": normalizar_texto(reg.get("uf", "")), "cep": reg.get("cep", ""),
            "horario": reg.get("horario", ""), "obs": reg.get("obs", ""), "telefone": reg.get("telefone", ""),
            "origem": "base",
        }
    if pdf.get("cidade"):
        return {
            "codigo": cod, "nome": nome, "endereco": pdf["endereco"], "bairro": "", "cidade": pdf["cidade"], "uf": "",
            "cep": pdf["cep"], "horario": "", "obs": "", "telefone": reg.get("telefone", ""), "origem": "pdf",
        }
    return {"codigo": cod, "nome": nome, "endereco": "", "bairro": "", "cidade": "", "uf": "", "cep": "",
            "horario": "", "obs": "", "telefone": reg.get("telefone", ""), "origem": ""}


def rotulo(info: dict[str, str]) -> str:
    """'L B LOG — R. HEROI DA FEB, 123 · VILA X · SAO PAULO'  (vai no card, na conferência e no romaneio)."""
    if not info.get("cidade"):
        cod = f" (cód. {info['codigo']})" if info.get("codigo") else ""
        return f"Transportadora {info.get('nome', '')}{cod} — sem endereço, cadastre na base de transportadoras"
    local = " · ".join(x for x in (info.get("endereco"), info.get("bairro"), info.get("cidade")) if x)
    return f"Transportadora {info.get('nome', '')} — {local}"


def campos_da_linha(info: dict[str, str], params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Campos da linha consolidada para levar na transportadora (motor e conferência usam)."""
    campos: dict[str, Any] = {
        "entrega_em": rotulo(info),
        "entrega_cliente_codigo": "",
        "cidade_destino": info.get("cidade", ""),
        "cidade": info.get("cidade", ""),
        "bairro_destino": info.get("bairro", ""),
        "bairro": info.get("bairro", ""),
        "cep_destino": info.get("cep", ""),
        "estado_destino": info.get("uf", ""),
        "enriquecido_mestre": "HUB" if info.get("cidade") else "NAO",
        "latitude": None,
        "longitude": None,
    }
    if info.get("horario"):
        campos["obs_recebimento"] = f"Transportadora recebe: {info['horario']}"
    if info.get("cidade"):
        campos["rota_logistica"] = resolver_rota_logistica(info["cidade"], params or {})
    return campos
