"""
Mesa de Comando Parametrizável — Superfine Logística.
"""

from __future__ import annotations

HORARIO_IN_EXPEDIENTE = "07:00"
HORARIO_LIMITE_RETORNO = "17:00"
TEMPO_DESCARGA_MINUTOS = 20
VELOCIDADE_MEDIA_KMH = 50
TARA_SPYDER_KG = 50
PERMITIR_SPYDER_NO_BAU = True
PESO_MAX_SPYDER_NO_BAU = 800
OBS_SPYDER_LEVE_BAU = "SPYDER LEVE - CARREGAR POR ÚLTIMO (PORTA DO BAÚ)"

COD_BLOQUEIO_FISCAL = "BLOQUEIO FISCAL"
COD_TRAVADO_COMERCIAL = "TRAVADO COMERCIAL"
COD_LIMITE_JORNADA = "LIMITE DE JORNADA"
COD_FROTA_INSUFICIENTE = "FROTA INSUFICIENTE"
COD_LIBERADO = "LIBERADO"
COD_RETIRA_FOB = "RETIRA FOB"
COD_TERCEIRO = "TERCEIRO"
COD_TERCEIRO_HUB = "ENTREGA_TERCEIRO_HUB"
COD_SUPERFINE_TRANSP = "1"
COD_REVISAO_OBRIGATORIA = "REVISAO_OBRIGATORIA"
COD_PROCESSANDO_IA = "PROCESSANDO_IA"
COD_BACKLOG_FUTURO = "BACKLOG_FUTURO"
STATUS_IA_NAO_APLICAVEL = "NAO_APLICAVEL"
STATUS_IA_CONCLUIDO = "CONCLUIDO"
STATUS_IA_ERRO = "ERRO_IA"

DISTANCIAS_BASE_KM = {
    "SANTA BARBARA D'OESTE": 0,
    "SAO PAULO": 120,
    "CAMPINAS": 80,
    "GUARULHOS": 130,
    "DIADEMA": 125,
    "MAUA": 130,
    "AMERICANA": 60,
    "JUNDIAI": 100,
    "VALINHOS": 90,
    "SAO BERNARDO DO CAMPO": 135,
    "CONTAGEM": 550,
    "LAGOA SANTA": 520,
    "ARAGUARI": 600,
    "GARIBALDI": 900,
    "GRAMADO DOS LOUREIROS": 920,
}

AJUSTE_VELOCIDADE_REGIAO = {
    "CAMPINAS": 1.20,
    "SAO PAULO": 1.15,
    "GUARULHOS": 1.15,
    "DIADEMA": 1.15,
    "MAUA": 1.15,
    "SAO BERNARDO DO CAMPO": 1.15,
    "CONTAGEM": 1.10,
    "LAGOA SANTA": 1.10,
    "DEFAULT": 1.00,
}

REGIAO_MACRO_MAP = {
    "SAO PAULO": "GRANDE_SP",
    "GUARULHOS": "GRANDE_SP",
    "DIADEMA": "GRANDE_SP",
    "MAUA": "GRANDE_SP",
    "SAO BERNARDO DO CAMPO": "GRANDE_SP",
    "JUNDIAI": "GRANDE_SP",
    "AMERICANA": "INTERIOR_SP",
    "CAMPINAS": "INTERIOR_SP",
    "VALINHOS": "INTERIOR_SP",
    "SANTA BARBARA D'OESTE": "BASE",
    "CONTAGEM": "MG",
    "LAGOA SANTA": "MG",
    "ARAGUARI": "MG",
    "GARIBALDI": "SUL",
    "GRAMADO DOS LOUREIROS": "SUL",
}

VEICULOS = {
    "VAN_MASTER": {
        "nome": "VAN MASTER",
        "capacidade_peso": 1800,
        "tipo": "BAU",
        "disponivel": False,
        "reserva": True,
    },
    "11.180_BAU_1": {
        "nome": "11.180 - BAÚ",
        "capacidade_peso": 6000,
        "tipo": "BAU",
        "disponivel": True,
        "reserva": False,
    },
    "11.180_BAU_2": {
        "nome": "11.180 - BAÚ",
        "capacidade_peso": 6100,
        "tipo": "BAU",
        "disponivel": True,
        "reserva": False,
    },
    "10.160_SYDER": {
        "nome": "10.160 - SYDER",
        "capacidade_peso": 4700,
        "tipo": "SYDER",
        "disponivel": True,
        "reserva": False,
    },
}

ARQUIVO_CADASTRO_CSV = "TESTE.xlsx - Planilha1.csv"
ARQUIVO_CADASTRO_XLSX = "TESTE.xlsx"

ROTULOS_ROTA = {
    "ROTA_CAPITAL": "CAPITAL",
    "ROTA_ABC": "ABC",
    "ROTA_LESTE": "LESTE",
    "ROTA_INTERIOR_RMC": "INTERIOR RMC",
    "ROTA_MG": "MG",
    "ROTA_SUL": "SUL",
    "ROTA_OUTROS": "OUTROS",
}

COLUNAS_BLOQUEIO_XLSB = (
    "PENDENCIAS",
    "EXPORTACAO",
    "ANTECIPADO",
    "FINANCEIRO",
    "COMERCIAL",
    "LOGISTICA",
)
