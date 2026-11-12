"""
Romaneio no MESMO formato da planilha "ROTA DIARIA - PROGRAMAÇÃO".

Usa templates/romaneio_modelo.xlsx (uma aba real da planilha, sem os dados):
mesmas fontes, bordas, mesclagens e larguras. Por caminhão, um bloco de 10
colunas (A-J, K-T, U-AD, AE-AN, AO-AX):

  linha 1  data | ENTREGAS DIARIAS - LOGISTICA
  linha 2  MOTORISTA ... CAPACIDADE MÁXIMA | Veículo
  linha 3  AJUDANTE                        | PLACA
  4-6      horário/km de saída e chegada, checagem de água/óleo (motorista preenche)
  7        CLIENTE | QTD | CONF NF 1 | CONF NF 2 | PESO | PEDIDO | BAIRRO | VOLUMES | H. CHEGADA | H. SAÍDA
  8        1ª ENTREGA
  9-26     entregas (mesmo pedido com vários itens numa linha: 2974/26/01,02 e =1000+500)
  27       TOTAL (=SUM)
  28-29    ATENÇÃO: MANTER NO CARRO / CONFERIDO

Ao lado (AZ-BG): COLETAS, RETIRAS, AGUARDANDO LOGÍSTICA (fila) e os pedidos
parados por REPRESENTANTE. Coluna BJ: OBSERVAÇÃO DE CLIENTE (horário de
recebimento). Até 5 caminhões por aba; mais caminhões, mais abas.
"""

from __future__ import annotations

import copy
import re
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Font
from openpyxl.utils import column_index_from_string as ci
from openpyxl.utils import get_column_letter as gl

MODELO = Path(__file__).resolve().parent / "templates" / "romaneio_modelo.xlsx"
BLOCOS = ("A", "K", "U", "AE", "AO")
LINHA_DADOS_INI, LINHA_DADOS_FIM, LINHA_TOTAL = 9, 26, 27
STATUS_COLETA = "TERCEIRO"
STATUS_RETIRA = "RETIRA FOB"


# ----------------------------------------------------------------- formatação
def pedido_curto(numero: str) -> tuple[str, str]:
    """'002974/26/001' -> ('2974/26', '01'), como a equipe escreve na planilha."""
    m = re.match(r"^0*(\d+)/(\d{2})/0*(\d+)$", (numero or "").strip())
    if not m:
        return numero or "", ""
    return f"{m.group(1)}/{m.group(2)}", f"{int(m.group(3)):02d}"


def _dd_mm(texto: str) -> str:
    m = re.match(r"^(\d{2})/(\d{2})", (texto or "").strip())
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.match(r"^\d{4}-(\d{2})-(\d{2})", (texto or "").strip())
    return f"{m.group(2)}/{m.group(1)}" if m else ""


def cliente_curto(nome: str, limite: int = 38) -> str:
    """Tira o apelido entre parênteses e encurta (a coluna é estreita)."""
    base = re.sub(r"\s*\([^)]*\)\s*$", "", (nome or "").strip()) or (nome or "")
    return base if len(base) <= limite else base[: limite - 1].rstrip() + "…"


def _destino(item: dict[str, Any]) -> str:
    local = (item.get("bairro_destino") or item.get("cidade_destino") or "").strip()
    if item.get("status") == "ENTREGA_TERCEIRO_HUB" or item.get("tipo_frete") == "ENTREGA_TERCEIRO_HUB":
        # Levar na transportadora: "TRANSPORTADORA - CIDADE", como na planilha
        transp = str(item.get("motivo_bloqueio") or "").split(" - ")[0].strip()
        cidade = (item.get("cidade_destino") or "").strip()
        local = " - ".join(x for x in (transp, cidade) if x) or local
    data = _dd_mm(str(item.get("data_producao") or ""))
    return f"{local} - {data}" if local and data else local or data


def _formula_peso(pesos: list[float]) -> float | str:
    pesos = [round(float(p), 1) for p in pesos]
    if len(pesos) == 1:
        return pesos[0]
    return "=" + "+".join(f"{p:g}" for p in pesos)


def agrupar_linhas(itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Mesmo cliente + mesmo pedido (ano) numa linha só, como na planilha:
    '2975/26/01,02,03' e peso '=50+70+80'. Mantém a ordem de entrega.
    """
    grupos: dict[tuple[str, str], dict[str, Any]] = {}
    ordem: list[tuple[str, str]] = []
    for it in itens:
        base, item = pedido_curto(str(it.get("numero_pedido", "")))
        chave = (str(it.get("cliente_codigo") or it.get("cliente", "")), base)
        if chave not in grupos:
            grupos[chave] = {"cliente": it.get("cliente", ""), "base": base, "itens": [], "pesos": [],
                             "destino": _destino(it), "partes": [], "data": _dd_mm(str(it.get("data_producao") or ""))}
            ordem.append(chave)
        g = grupos[chave]
        if item and item not in g["itens"]:
            g["itens"].append(item)
        g["pesos"].append(float(it.get("peso_kg") or 0))
        if it.get("parte"):
            g["partes"].append(str(it["parte"]))
    linhas = []
    for chave in ordem:
        g = grupos[chave]
        pedido = g["base"] + (("/" + ",".join(g["itens"])) if g["itens"] else "")
        if g["partes"]:
            pedido += f" (parte {', '.join(g['partes'])})"
        linhas.append({"cliente": cliente_curto(g["cliente"]), "peso": _formula_peso(g["pesos"]),
                       "pedido": pedido, "destino": g["destino"], "data": g["data"]})
    return linhas


# ----------------------------------------------------------------- escrita
def _set(ws, linha: int, col: int, valor: Any) -> None:
    c = ws.cell(linha, col)
    if isinstance(c, MergedCell):
        return
    c.value = valor


def _copiar_estilo(ws, origem: tuple[int, int], destino: tuple[int, int]) -> None:
    ws.cell(*destino)._style = copy.copy(ws.cell(*origem)._style)


def _escrever_linha_entrega(ws, linha: int, c0: int, d: dict[str, Any]) -> None:
    if linha > LINHA_DADOS_FIM:  # continuação abaixo do rodapé: copia o estilo de uma linha de dados
        for k in range(10):
            _copiar_estilo(ws, (LINHA_DADOS_INI, c0 + k), (linha, c0 + k))
    _set(ws, linha, c0, d["cliente"])
    _set(ws, linha, c0 + 4, d["peso"])
    _set(ws, linha, c0 + 5, d["pedido"])
    _set(ws, linha, c0 + 6, d["destino"])


def _escrever_bloco(ws, c0: int, veiculo: dict[str, Any], dia: date | None) -> None:
    equipe = veiculo.get("equipe") or {}
    cap = veiculo.get("capacidade_kg")
    cap_txt = f"   CAPACIDADE MÁXIMA {int(cap):,} KG".replace(",", ".") if cap else ""
    if dia:
        _set(ws, 1, c0 + 4, datetime(dia.year, dia.month, dia.day))
        ws.cell(1, c0 + 4).number_format = "dd/mm/yyyy"
    _set(ws, 2, c0, f"MOTORISTA: {equipe.get('motorista', '')}{cap_txt}")
    _set(ws, 2, c0 + 8, f"Veículo: {veiculo.get('nome', '')}")
    _set(ws, 3, c0, f"AJUDANTE: {equipe.get('ajudante', '')}")
    _set(ws, 3, c0 + 8, f"PLACA: {equipe.get('placa', '')}")

    linha = LINHA_DADOS_INI
    proxima = linha

    def escrever(linhas: list[dict[str, Any]]) -> None:
        nonlocal proxima
        for d in linhas:
            if proxima == LINHA_DADOS_FIM + 1:
                proxima = 31  # rodapé fica em 27-29; continua abaixo
                _set(ws, 30, c0, "CONTINUAÇÃO")
                ws.cell(30, c0).font = Font(bold=True)
            _escrever_linha_entrega(ws, proxima, c0, d)
            proxima += 1

    escrever(agrupar_linhas(veiculo.get("itens", [])))
    retorno = veiculo.get("itens_retorno") or []
    if retorno:
        if proxima <= LINHA_DADOS_FIM:
            _set(ws, proxima, c0, "2ª ENTREGA")
            ws.cell(proxima, c0).font = Font(bold=True)
            proxima += 1
        escrever(agrupar_linhas(retorno))

    col_peso = gl(c0 + 4)
    ultima = max(proxima - 1, LINHA_DADOS_FIM)
    faixas = f"{col_peso}{LINHA_DADOS_INI}:{col_peso}{min(ultima, LINHA_DADOS_FIM)}"
    if ultima > LINHA_DADOS_FIM:
        faixas += f",{col_peso}31:{col_peso}{ultima}"
    _set(ws, LINHA_TOTAL, c0 + 4, f"=SUM({faixas})")


def _painel_lateral(ws, secoes: list[tuple[str, list[dict[str, Any]]]], observacoes: list[str]) -> None:
    """AZ-BG: COLETAS / RETIRAS / AGUARDANDO LOGÍSTICA / REPRESENTANTE X. BJ: observações."""
    estilo_titulo = (5, ci("BA"))
    linha = 6
    for titulo, itens in secoes:
        if not itens:
            continue
        if titulo != "COLETAS":
            linha += 1
            _copiar_estilo(ws, estilo_titulo, (linha, ci("BA")))
            _set(ws, linha, ci("BA"), titulo)
            linha += 1
        for d in agrupar_linhas(itens):
            _set(ws, linha, ci("AZ"), d["data"])
            _set(ws, linha, ci("BA"), d["cliente"])
            _set(ws, linha, ci("BE"), d["peso"])
            _set(ws, linha, ci("BF"), d["pedido"])
            _set(ws, linha, ci("BG"), d["destino"])
            linha += 1
    for i, obs in enumerate(observacoes, start=2):
        _set(ws, i, ci("BJ"), obs)


def gerar_romaneio_planilha(
    roteirizacao: dict[str, Any],
    consolidados: list[dict[str, Any]],
    frota: list[dict[str, Any]],
    dia: date | None = None,
    somente_veiculo: str = "",
) -> bytes:
    """Gera o .xlsx no formato da planilha. `somente_veiculo` = romaneio de um caminhão."""
    por_id = {c.get("id_item") or c.get("numero_pedido"): c for c in consolidados}

    def enriquecer(it: dict[str, Any]) -> dict[str, Any]:
        c = por_id.get(it.get("id_item") or it.get("numero_pedido")) or {}
        return {**c, **{k: v for k, v in it.items() if v not in ("", None)}}

    itens_por_veiculo = roteirizacao.get("itens_por_veiculo", {})
    retorno_por_veiculo = roteirizacao.get("itens_retorno_por_veiculo", {})
    equipe = roteirizacao.get("equipe_por_veiculo", {})
    rotas = {r.get("veiculo_id"): r for r in roteirizacao.get("rotas", [])}

    veiculos = []
    ids_frota = [str(v.get("id")) for v in frota]
    for vid in ids_frota + [v for v in itens_por_veiculo if v not in ids_frota]:
        cad = next((v for v in frota if str(v.get("id")) == vid), {})
        tem_carga = bool(itens_por_veiculo.get(vid) or retorno_por_veiculo.get(vid))
        if somente_veiculo and vid != somente_veiculo:
            continue
        if not tem_carga and not cad.get("ativo", False):
            continue
        ordenar = lambda l: sorted(l, key=lambda i: int(str(i.get("sequencia_lifo") or 0) or 0))  # noqa: E731
        veiculos.append({
            "id": vid,
            "nome": cad.get("nome") or rotas.get(vid, {}).get("veiculo_nome") or vid,
            "capacidade_kg": cad.get("capacidade_kg") or rotas.get(vid, {}).get("capacidade_kg"),
            "equipe": {**{"placa": cad.get("placa", "")}, **{k: v for k, v in (equipe.get(vid) or {}).items() if v}},
            "itens": [enriquecer(i) for i in ordenar(itens_por_veiculo.get(vid, []))],
            "itens_retorno": [enriquecer(i) for i in ordenar(retorno_por_veiculo.get(vid, []))],
        })

    wb = openpyxl.load_workbook(MODELO)
    modelo = wb.worksheets[0]
    grupos = [veiculos[i:i + 5] for i in range(0, max(len(veiculos), 1), 5)] or [[]]
    folhas = [modelo] + [wb.copy_worksheet(modelo) for _ in grupos[1:]]
    for n, (ws, grupo) in enumerate(zip(folhas, grupos), start=1):
        ws.title = "ROMANEIO" if len(folhas) == 1 else f"ROMANEIO {n}"
        for b, veiculo in zip(BLOCOS, grupo):
            _escrever_bloco(ws, ci(b), veiculo, dia)
        if dia:
            for b in BLOCOS[len(grupo):]:
                _set(ws, 1, ci(b) + 4, datetime(dia.year, dia.month, dia.day))
                ws.cell(1, ci(b) + 4).number_format = "dd/mm/yyyy"

    # Painel lateral e observações só na primeira aba
    ativos = [c for c in consolidados]
    coletas = [c for c in ativos if c.get("status") == STATUS_COLETA and not c.get("pendencias")]
    retiras = [c for c in ativos if c.get("status") == STATUS_RETIRA and not c.get("pendencias")]
    fila = [enriquecer(b) for b in roteirizacao.get("backlog", [])]
    parados: dict[str, list[dict[str, Any]]] = {}
    for c in ativos:
        if c.get("pendencias"):
            parados.setdefault(c.get("representante") or "NÃO IDENTIFICADO", []).append(c)
    secoes = [("COLETAS", coletas), ("RETIRAS", retiras), ("AGUARDANDO LOGISTICA", fila)]
    secoes += [(f"REPRESENTANTE {rep}", itens) for rep, itens in sorted(parados.items())]
    observacoes = []
    vistos: set[str] = set()
    for v in veiculos:
        for i in v["itens"] + v["itens_retorno"]:
            texto = str(i.get("obs_recebimento") or "").strip()
            if i.get("entrega_em"):
                texto = f"ENTREGAR EM {i['entrega_em']}" + (f" | {texto}" if texto else "")
            chave = f"{i.get('cliente_codigo')}|{texto}"
            if texto and chave not in vistos:
                vistos.add(chave)
                observacoes.append(f"{cliente_curto(i.get('cliente', ''), 24)} - {texto}")
    if not somente_veiculo:
        _painel_lateral(folhas[0], secoes, observacoes)
    elif veiculos:
        # Romaneio de um caminhão: imprime só o bloco dele
        folhas[0].print_area = f"A1:J{max(29, LINHA_DADOS_FIM)}"
        _painel_lateral(folhas[0], [], observacoes)

    saida = BytesIO()
    wb.save(saida)
    return saida.getvalue()
