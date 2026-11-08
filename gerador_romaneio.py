"""
Gerador do Romaneio de Carga — layout legado Excel por veículo e romaneio por caminhão.

Colunas legado: CLIENTE | PESO KG | PEDIDO | BAIRRO
Romaneio físico: Sequência | Pedido | Cliente | Cidade | Peso | Obs | Assinatura
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

COLUNAS = ("CLIENTE", "PESO KG", "PEDIDO", "BAIRRO")

COLUNAS_ROMANEIO_FISICO = (
    "Sequência",
    "Pedido",
    "Cliente",
    "Cidade",
    "Peso (KG)",
    "Observação Logística",
    "Assinatura / Recebedor",
)

VERDE_SISTEMA = "16A34A"
VERDE_CLARO = "DCFCE7"
BORDA_FINA = Side(style="thin", color="CCCCCC")
BORDA_MEDIA = Side(style="thin", color="666666")

_MAP_TIPO_FRETE = {
    "RETIRA_FOB": "FOB",
    "ENTREGA_TERCEIRO_HUB": "HUB",
    "ENTREGA_TERCEIRO": "TERCEIRO",
    "ENTREGA_DIRETA": "DIRETA",
}


def _ordenar_itens_lifo(itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Maior sequencia_lifo primeiro (ordem de carregamento no baú)."""
    return sorted(
        itens,
        key=lambda item: int(str(item.get("sequencia_lifo") or "0") or 0),
        reverse=True,
    )


def _titulo_veiculo(rota: dict[str, Any]) -> str:
    nome = str(rota.get("veiculo_nome") or rota.get("veiculo_id") or "VEÍCULO").strip()
    return nome.upper()


def _escrever_bloco_veiculo(
    ws,
    linha_inicio: int,
    titulo: str,
    itens: list[dict[str, Any]],
) -> int:
    """Escreve bloco do veículo; retorna próxima linha livre."""
    fill_titulo = PatternFill("solid", fgColor=VERDE_SISTEMA)
    fill_header = PatternFill("solid", fgColor=VERDE_CLARO)
    font_titulo = Font(color="FFFFFF", bold=True, size=12)
    font_header = Font(bold=True, size=11)
    font_total = Font(bold=True)
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    borda = Border(left=BORDA_FINA, right=BORDA_FINA, top=BORDA_FINA, bottom=BORDA_FINA)

    row = linha_inicio

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    cell_titulo = ws.cell(row=row, column=1, value=titulo)
    cell_titulo.fill = fill_titulo
    cell_titulo.font = font_titulo
    cell_titulo.alignment = align_center
    row += 1

    for col_idx, header in enumerate(COLUNAS, start=1):
        cell = ws.cell(row=row, column=col_idx, value=header)
        cell.fill = fill_header
        cell.font = font_header
        cell.alignment = align_center
        cell.border = borda
    row += 1

    peso_total = 0.0
    for item in itens:
        peso = float(item.get("peso_kg") or 0)
        peso_total += peso
        valores = (
            str(item.get("cliente") or ""),
            peso,
            _pedido_com_of(item),
            str(item.get("bairro_destino") or ""),
        )
        for col_idx, valor in enumerate(valores, start=1):
            cell = ws.cell(row=row, column=col_idx, value=valor)
            cell.alignment = align_left if col_idx in (1, 4) else align_center
            cell.border = borda
            if col_idx == 2:
                cell.number_format = "#,##0.00"
        row += 1

    cell_rotulo = ws.cell(row=row, column=1, value="TOTAL DE PESO")
    cell_rotulo.font = font_total
    cell_rotulo.alignment = Alignment(horizontal="right", vertical="center")
    cell_rotulo.border = borda
    cell_rotulo.fill = fill_header

    cell_peso = ws.cell(row=row, column=2, value=peso_total)
    cell_peso.font = font_total
    cell_peso.number_format = "#,##0.00"
    cell_peso.alignment = align_center
    cell_peso.border = borda
    cell_peso.fill = fill_header

    for col in range(3, 5):
        cell = ws.cell(row=row, column=col, value="")
        cell.border = borda
        cell.fill = fill_header

    return row + 2


def gerar_romaneio_xlsx(roteirizacao: dict[str, Any]) -> bytes:
    """Gera bytes do .xlsx a partir do payload roteirizacao.json."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Romaneio"

    rotas = roteirizacao.get("rotas") or []
    itens_por_veiculo: dict[str, list] = roteirizacao.get("itens_por_veiculo") or {}

    ws.merge_cells("A1:D1")
    titulo_doc = ws.cell(row=1, column=1, value=f"ROMANEIO DE CARGA — {date.today().strftime('%d/%m/%Y')}")
    titulo_doc.font = Font(bold=True, size=14)
    titulo_doc.alignment = Alignment(horizontal="center", vertical="center")

    linha = 3
    blocos = 0

    for rota in rotas:
        veiculo_id = str(rota.get("veiculo_id") or "")
        itens_raw = itens_por_veiculo.get(veiculo_id) or []
        if not itens_raw:
            continue

        itens = _ordenar_itens_lifo(list(itens_raw))
        linha = _escrever_bloco_veiculo(ws, linha, _titulo_veiculo(rota), itens)
        blocos += 1

    if blocos == 0:
        ws.cell(row=3, column=1, value="Nenhum pedido alocado em veículos.")

    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 28

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def nome_arquivo_romaneio(session_id: str = "") -> str:
    sufixo = session_id[:8] if session_id else "export"
    return f"romaneio_{sufixo}_{date.today().isoformat()}.xlsx"


def _sanitizar_nome_arquivo(texto: str) -> str:
    limpo = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in texto.strip())
    return limpo or "veiculo"


def nome_arquivo_romaneio_caminhao(caminhao_id: str) -> str:
    vid = _sanitizar_nome_arquivo(caminhao_id)
    return f"Romaneio_Caminhao_{vid}_{date.today().isoformat()}.xlsx"


def _ordenar_itens_entrega(itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordem de entrega: sequencia_lifo crescente (1º descarregado = seq. 1)."""
    return sorted(
        itens,
        key=lambda item: int(str(item.get("sequencia_lifo") or "0") or 0),
    )


def _pedido_com_of(item: dict[str, Any]) -> str:
    """No romaneio, o pedido sai com a OF: o mesmo pedido/item pode ter várias."""
    numero = str(item.get("numero_pedido") or "")
    of = str(item.get("of_ano") or "")
    return f"{numero} OF {of}" if of else numero


def _observacao_logistica(
    item: dict[str, Any],
    consolidados_por_pedido: dict[str, dict[str, Any]] | None,
) -> str:
    partes: list[str] = []
    numero = str(item.get("numero_pedido") or "")
    mapa = consolidados_por_pedido or {}
    cons = mapa.get(str(item.get("id_item") or "")) or mapa.get(numero) or {}

    status = str(cons.get("status") or "").strip()
    tipo = str(cons.get("tipo_frete") or "").strip()
    if status and status.upper() not in ("LIBERADO", ""):
        partes.append(status)
    elif tipo:
        partes.append(_MAP_TIPO_FRETE.get(tipo, tipo.replace("ENTREGA_", "")))

    obs = str(cons.get("observacao_comercial") or "").strip()
    if obs:
        partes.append(obs)

    if not partes:
        motivo = str(cons.get("motivo_alocacao") or "").strip()
        if motivo:
            partes.append(motivo)

    return " | ".join(partes)


def _auto_ajustar_colunas(ws, col_count: int, min_width: int = 10, max_width: int = 48) -> None:
    for col in range(1, col_count + 1):
        letter = get_column_letter(col)
        max_len = min_width
        for row in ws.iter_rows(min_col=col, max_col=col):
            for cell in row:
                if cell.value is None:
                    continue
                max_len = max(max_len, min(len(str(cell.value)), max_width))
        if col == col_count:
            max_len = max(max_len, 28)
        ws.column_dimensions[letter].width = max_len + 2


def gerar_romaneio_caminhao_xlsx(
    roteirizacao: dict[str, Any],
    caminhao_id: str,
    consolidados_por_pedido: dict[str, dict[str, Any]] | None = None,
) -> bytes:
    """Gera romaneio físico (.xlsx) pronto para impressão — um caminhão."""
    rotas = roteirizacao.get("rotas") or []
    itens_por_veiculo: dict[str, list] = roteirizacao.get("itens_por_veiculo") or {}
    itens_retorno: dict[str, list] = roteirizacao.get("itens_retorno_por_veiculo") or {}

    import config as app_config

    is_retorno = caminhao_id.endswith(app_config.SUFIXO_VIAGEM_RETORNO)
    veiculo_base = (
        caminhao_id[: -len(app_config.SUFIXO_VIAGEM_RETORNO)] if is_retorno else caminhao_id
    )

    rota_meta = next(
        (r for r in rotas if str(r.get("veiculo_id") or "") == veiculo_base),
        None,
    )
    if rota_meta is None:
        raise ValueError(f"Caminhão não encontrado: {caminhao_id}")

    if is_retorno:
        itens_raw = list(itens_retorno.get(veiculo_base) or [])
    else:
        itens_raw = list(itens_por_veiculo.get(caminhao_id) or [])
    itens = _ordenar_itens_entrega(itens_raw)
    peso_total = sum(float(i.get("peso_kg") or 0) for i in itens)

    nome_base = str(rota_meta.get("veiculo_nome") or veiculo_base).strip()
    nome_veiculo = f"{nome_base} - Retorno" if is_retorno else nome_base
    id_exibicao = caminhao_id if is_retorno else veiculo_base
    data_hoje = date.today().strftime("%d/%m/%Y")
    num_cols = len(COLUNAS_ROMANEIO_FISICO)

    wb = Workbook()
    ws = wb.active
    ws.title = "Romaneio"

    fill_header = PatternFill("solid", fgColor=VERDE_CLARO)
    font_titulo = Font(bold=True, size=14)
    font_meta = Font(size=11)
    font_header = Font(bold=True, size=11)
    font_normal = Font(size=10)
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    borda = Border(
        left=BORDA_MEDIA,
        right=BORDA_MEDIA,
        top=BORDA_MEDIA,
        bottom=BORDA_MEDIA,
    )

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
    c1 = ws.cell(row=1, column=1, value="Romaneio de Carga - Superfine Steel")
    c1.font = font_titulo
    c1.alignment = align_center

    meta_linhas = [
        f"Data: {data_hoje}",
        f"Veículo: {nome_veiculo} ({id_exibicao})",
        f"Carga Total: {peso_total:,.2f} KG".replace(",", " ").replace(".", ",").replace(" ", "."),
    ]
    row = 2
    for texto in meta_linhas:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=num_cols)
        cell = ws.cell(row=row, column=1, value=texto)
        cell.font = font_meta
        cell.alignment = align_left
        row += 1

    row += 1
    header_row = row
    for col_idx, header in enumerate(COLUNAS_ROMANEIO_FISICO, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=header)
        cell.fill = fill_header
        cell.font = font_header
        cell.alignment = align_center
        cell.border = borda
    row += 1

    if not itens:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=num_cols)
        cell = ws.cell(row=row, column=1, value="Nenhum pedido alocado neste veículo.")
        cell.alignment = align_center
        cell.font = font_normal
    else:
        for seq, item in enumerate(itens, start=1):
            peso = float(item.get("peso_kg") or 0)
            valores = (
                seq,
                _pedido_com_of(item),
                str(item.get("cliente") or ""),
                str(item.get("cidade_destino") or ""),
                peso,
                _observacao_logistica(item, consolidados_por_pedido),
                "",
            )
            for col_idx, valor in enumerate(valores, start=1):
                cell = ws.cell(row=row, column=col_idx, value=valor)
                cell.font = font_normal
                cell.border = borda
                if col_idx in (1, 5):
                    cell.alignment = align_center
                    if col_idx == 5:
                        cell.number_format = "#,##0.00"
                elif col_idx == 7:
                    cell.alignment = Alignment(horizontal="left", vertical="bottom")
                else:
                    cell.alignment = align_left
            row += 1

    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0

    _auto_ajustar_colunas(ws, num_cols)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
