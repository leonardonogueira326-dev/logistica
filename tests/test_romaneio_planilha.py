"""O romaneio sai no formato da planilha ROTA DIARIA."""
from __future__ import annotations

import io
from datetime import date

import openpyxl

from romaneio_planilha import agrupar_linhas, gerar_romaneio_planilha, pedido_curto


def test_pedido_no_formato_da_planilha():
    assert pedido_curto("002974/26/001") == ("2974/26", "01")
    assert pedido_curto("000233/26/003") == ("233/26", "03")


def test_mesmo_pedido_numa_linha_com_formula_de_peso():
    itens = [
        {"cliente": "AQSEPTENCE GROUP (AQSEPTENCE)", "cliente_codigo": "1351", "numero_pedido": "002974/26/001",
         "peso_kg": 1000, "cidade_destino": "SAO BERNARDO DO CAMPO", "data_producao": "19/06/26"},
        {"cliente": "AQSEPTENCE GROUP (AQSEPTENCE)", "cliente_codigo": "1351", "numero_pedido": "002974/26/002",
         "peso_kg": 500, "cidade_destino": "SAO BERNARDO DO CAMPO", "data_producao": "19/06/26"},
    ]
    (linha,) = agrupar_linhas(itens)
    assert linha["cliente"] == "AQSEPTENCE GROUP"
    assert linha["pedido"] == "2974/26/01,02"
    assert linha["peso"] == "=1000+500"
    assert linha["destino"] == "SAO BERNARDO DO CAMPO - 19/06"


def test_levar_na_transportadora_mostra_transportadora_e_cidade():
    (linha,) = agrupar_linhas([{
        "cliente": "ZAGONEL S.A. (ZAGONEL)", "cliente_codigo": "5143", "numero_pedido": "002923/26/001",
        "peso_kg": 275, "status": "ENTREGA_TERCEIRO_HUB", "motivo_bloqueio": "TRANSGOSS GT TRANSPORTES - R MONICA AP",
        "cidade_destino": "GUARULHOS", "bairro_destino": "R MONICA AP.", "data_producao": "19/06/26",
    }])
    assert linha["destino"] == "TRANSGOSS GT TRANSPORTES - GUARULHOS - 19/06"


def test_blocos_por_caminhao_com_equipe_total_e_observacao():
    rote = {
        "rotas": [{"veiculo_id": "BAU", "veiculo_nome": "11.180 - BAÚ", "capacidade_kg": 6000}],
        "itens_por_veiculo": {"BAU": [
            {"numero_pedido": "003047/26/001", "id_item": "a", "cliente": "REAL PERFIL (REALPERFIL)",
             "cliente_codigo": "3144", "peso_kg": 1500, "sequencia_lifo": "1", "cidade_destino": "SAO PAULO"},
        ]},
        "equipe_por_veiculo": {"BAU": {"motorista": "JOÃO", "ajudante": "DANIEL", "placa": "DCU-0A57"}},
        "backlog": [],
    }
    consolidados = [{"id_item": "a", "obs_recebimento": "SÓ ABRE AS 8:00", "data_producao": "23/06/26"}]
    frota = [{"id": "BAU", "nome": "11.180 - BAÚ", "capacidade_kg": 6000, "ativo": True, "placa": ""}]
    wb = openpyxl.load_workbook(io.BytesIO(gerar_romaneio_planilha(rote, consolidados, frota, date(2026, 6, 19))))
    ws = wb.worksheets[0]
    assert ws["A2"].value.startswith("MOTORISTA: JOÃO") and "6.000 KG" in ws["A2"].value
    assert ws["I2"].value == "Veículo: 11.180 - BAÚ"
    assert ws["A3"].value == "AJUDANTE: DANIEL" and ws["I3"].value == "PLACA: DCU-0A57"
    assert ws["A7"].value == "CLIENTE" and ws["F7"].value == "PEDIDO"
    assert (ws["A9"].value, ws["E9"].value, ws["F9"].value) == ("REAL PERFIL", 1500, "3047/26/01")
    assert ws["G9"].value == "SAO PAULO - 23/06"
    assert ws["E27"].value == "=SUM(E9:E26)"
    assert ws["BJ2"].value == "REAL PERFIL - SÓ ABRE AS 8:00"
    assert ws["E1"].value.date() == date(2026, 6, 19)
