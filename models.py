"""
Modelos de dados — Fase 1 + Fase 2.
Todos os campos são tipos simples (str/float), sem listas.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PedidoFaturamento:
    """Pedido extraído do PDF de Solicitação de Faturamento."""

    numero_pedido: str = ""
    numero_pedido_norm: str = ""
    sequencia: str = ""
    cliente_codigo: str = ""
    cliente_nome: str = ""
    peso_kg: float = 0.0
    peso_raw: str = ""
    valor_tt: float = 0.0
    valor_tt_raw: str = ""
    cidade: str = ""
    estado: str = ""
    bairro: str = ""
    cidade_destino: str = ""
    estado_destino: str = ""
    bairro_destino: str = ""
    cep: str = ""
    cep_destino: str = ""
    representante: str = ""
    rota_logistica: str = ""
    enriquecido_mestre: str = "NAO"
    observacao_comercial: str = ""
    descricao_item: str = ""
    transportadora: str = ""
    transportadora_codigo: str = ""
    data_producao: str = ""
    of_ano: str = ""
    tipo_frete: str = ""
    aprendizado_aplicado: str = "NAO"
    is_spyder: str = "NAO"
    is_dimensao_longa: str = "NAO"
    exige_syder: str = "NAO"
    bloco_bruto: str = ""
    erro_extracao: str = ""


@dataclass
class RetencaoFiscal:
    """Linha da última aba do XLSB de material não faturado."""

    data: str = ""
    cliente: str = ""
    pedido_raw: str = ""
    pedidos_expandidos: str = ""
    peso_kg: float = 0.0
    motivo_coluna: str = ""
    valor_bloqueio: str = ""
    representante: str = ""
    obs_faturar: str = ""
    erro_extracao: str = ""


@dataclass
class EventoEmail:
    """Evento do relatório de canhotos/coletas no corpo do e-mail MSG."""

    data: str = ""
    cliente: str = ""
    nf: str = ""
    volume: str = ""
    peso_kg: str = ""
    bairro: str = ""
    cidade: str = ""
    observacao: str = ""
    tipo_evento: str = ""
    erro_extracao: str = ""


@dataclass
class PedidoConsolidado:
    """Visão unificada após cruzamento das fontes."""

    numero_pedido: str = ""
    numero_pedido_norm: str = ""
    cliente: str = ""
    cliente_codigo: str = ""
    peso_kg: float = 0.0
    valor_tt: float = 0.0
    cidade: str = ""
    estado: str = ""
    bairro: str = ""
    cidade_destino: str = ""
    estado_destino: str = ""
    bairro_destino: str = ""
    cep: str = ""
    cep_destino: str = ""
    representante: str = ""
    rota_logistica: str = ""
    enriquecido_mestre: str = "NAO"
    status: str = ""
    motivo_bloqueio: str = ""
    tipo_frete: str = ""
    is_spyder: str = "NAO"
    is_dimensao_longa: str = "NAO"
    exige_syder: str = "NAO"
    motivo_alocacao: str = ""
    fontes: str = ""
    auditoria: str = ""
    observacao_comercial: str = ""
    data_producao: str = ""
    revisao_obrigatoria: str = "NAO"
    motivo_quarentena: str = ""
    palavra_chave_quarentena: str = ""


@dataclass
class ItemRota:
    """Pedido alocado em uma rota de veículo."""

    numero_pedido: str = ""
    cliente: str = ""
    cliente_codigo: str = ""
    representante: str = ""
    bairro_destino: str = ""
    cidade_destino: str = ""
    estado_destino: str = ""
    cep_destino: str = ""
    rota_logistica: str = ""
    peso_kg: float = 0.0
    sequencia_lifo: str = ""
    tipo_item: str = "PEDIDO"
    is_spyder: str = "NAO"
    is_dimensao_longa: str = "NAO"
    exige_syder: str = "NAO"
    enriquecido_mestre: str = "NAO"


@dataclass
class RotaVeiculo:
    """Rota montada para um veículo da frota."""

    veiculo_id: str = ""
    veiculo_nome: str = ""
    regiao_predominante: str = ""
    rota_vocacao: str = ""
    capacidade_kg: float = 0.0
    peso_alocado_kg: float = 0.0
    eficiencia_pct: str = ""
    tempo_total_min: str = ""
    retorno_previsto: str = ""
    qtd_paradas: str = ""
    pedidos_csv: str = ""


@dataclass
class ResultadoRoteirizacao:
    """Resultado completo da roteirização."""

    rotas: str = ""
    backlog_csv: str = ""
    total_alocados: str = ""
    total_backlog: str = ""
