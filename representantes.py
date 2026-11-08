"""
Representante de cada cliente a partir da base de clientes da empresa
(base-de-clientes.xlsx, atualizada pelo sistema da empresa).

Só o representante é lido daqui: a cidade da base é a do cadastro do cliente
e pode ser diferente do destino de entrega do PDF.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from normalizador import normalizar_codigo_cliente, normalizar_texto

RAIZ = Path(__file__).resolve().parent
ARQUIVO_APRENDIDOS = RAIZ / "data" / "representantes_aprendidos.json"
NOMES_BASE = ("base-de-clientes.xlsx", "base-de-clientes1.xlsx")

_cache: dict[str, tuple[float, dict[str, dict[str, str]]]] = {}


def localizar_base(pastas: list[Path] | None = None) -> Path | None:
    """A base mais recente encontrada na pasta de dados ou na raiz do projeto."""
    candidatos = []
    for pasta in [*(pastas or []), RAIZ]:
        for nome in NOMES_BASE:
            p = Path(pasta) / nome
            if p.is_file():
                candidatos.append(p)
    return max(candidatos, key=lambda p: p.stat().st_mtime) if candidatos else None


def carregar_representantes(caminho: Path | None) -> dict[str, dict[str, str]]:
    """codigo_cliente -> {representante, representante_codigo}. Cache por data do arquivo."""
    if not caminho:
        return {}
    chave = str(caminho.resolve())
    mtime = caminho.stat().st_mtime
    if chave in _cache and _cache[chave][0] == mtime:
        return _cache[chave][1]

    import openpyxl

    mapa: dict[str, dict[str, str]] = {}
    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            linhas = ws.iter_rows(values_only=True)
            cab = [normalizar_texto(str(c or "")) for c in next(linhas, [])]
            if "CODIGO" not in cab:
                continue
            idx = {nome: i for i, nome in enumerate(cab)}
            i_cod = idx["CODIGO"]
            i_fant = idx.get("REPRESENTANTE_FANTASIA")
            i_razao = idx.get("REPRESENTANTE_RAZAO")
            i_rep_cod = idx.get("CODIGO_REPRESENTANTE")
            for linha in linhas:
                codigo = normalizar_codigo_cliente(str(linha[i_cod] or ""))
                if not codigo:
                    continue
                nome = ""
                for i in (i_fant, i_razao):
                    if i is not None and linha[i]:
                        nome = str(linha[i]).strip()
                        break
                if nome:
                    mapa[codigo] = {
                        "representante": normalizar_texto(nome),
                        "representante_codigo": str(linha[i_rep_cod] or "").strip() if i_rep_cod is not None else "",
                    }
            break
    finally:
        wb.close()
    _cache[chave] = (mtime, mapa)
    return mapa


def limpar_representante_pdf(texto: str) -> str:
    """
    O PDF às vezes cola texto de outras colunas no nome do representante:
    'MARCOS CASTRO (TECNOACO) CONDIÇÃO DE PGTO: 14/21/28 DDL' -> 'MARCOS CASTRO'.
    """
    nome = normalizar_texto(texto or "")
    nome = re.split(r"\s+CONDI[CÇ][AÃ]O\b|\s+PARCELAS\b|\s+DESTINO\b|\s+TRANSP\b", nome)[0]
    nome = re.sub(r"\s*\([^)]*\)\s*", " ", nome)
    return re.sub(r"\s+", " ", nome).strip(" -")


def carregar_aprendidos() -> dict[str, str]:
    """Correções feitas pelo operador: codigo_cliente -> representante."""
    try:
        bruto = json.loads(ARQUIVO_APRENDIDOS.read_text(encoding="utf-8"))
        return {k: v for k, v in bruto.items() if not k.startswith("_") and isinstance(v, str)}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def aprender_representante(codigo_cliente: str, representante: str) -> bool:
    """
    O operador corrigiu o representante de um cliente: vale para as próximas
    solicitações, por cima da base de clientes.
    """
    codigo = normalizar_codigo_cliente(codigo_cliente)
    nome = normalizar_texto(representante or "")
    if not codigo or not nome or nome == "NÃO IDENTIFICADO":
        return False
    dados = carregar_aprendidos()
    if dados.get(codigo) == nome:
        return False
    dados[codigo] = nome
    ARQUIVO_APRENDIDOS.parent.mkdir(parents=True, exist_ok=True)
    payload = {"_descricao": "Representante corrigido pelo operador (codigo_cliente -> nome)", **dict(sorted(dados.items()))}
    ARQUIVO_APRENDIDOS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
