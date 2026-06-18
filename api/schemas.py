"""Schemas Pydantic — espelham os dataclasses de models.py."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PedidoConsolidadoSchema(BaseModel):
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


class ConsolidadoPatchSchema(BaseModel):
    cliente: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    cep: Optional[str] = None
    representante: Optional[str] = None
    status: Optional[str] = None


class ResumoIngestaoSchema(BaseModel):
    pedidos_pdf: str = "0"
    retencoes_xlsb: str = "0"
    eventos_email: str = "0"
    consolidados: str = "0"
    enriquecidos_mestre: str = "0/0"
    cadastro_clientes: str = "0"
    liberados: str = "0"
    bloqueio_fiscal: str = "0"
    travado_comercial: str = "0"
    retira_fob: str = "0"
    terceiros: str = "0"
    terceiros_hub: str = "0"
    revisao_obrigatoria: str = "0"
    avisos: str = "NENHUM"
    erros: str = "NENHUM"


class IngestaoResponseSchema(BaseModel):
    session_id: str
    resumo: ResumoIngestaoSchema
    consolidados: list[PedidoConsolidadoSchema]
    avisos: list[str] = Field(default_factory=list)
    erros: list[str] = Field(default_factory=list)


class UploadResponseSchema(BaseModel):
    session_id: str
    files_saved: list[str]
    warnings: list[str] = Field(default_factory=list)


class ConsolidadosListSchema(BaseModel):
    session_id: str
    validated: bool = False
    resumo: Optional[ResumoIngestaoSchema] = None
    consolidados: list[PedidoConsolidadoSchema] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)


class ValidacaoConfirmarSchema(BaseModel):
    session_id: str
    validated: bool = True
    total_consolidados: int = 0
    message: str = ""
    regras_salvas: int = 0


class ValidacaoConfirmarBodySchema(BaseModel):
    """Regras novas: dict plano codigo_palavra -> status."""
    regras_novas: dict[str, str] = Field(default_factory=dict)


class ItemRotaSchema(BaseModel):
    numero_pedido: str = ""
    cliente: str = ""
    cliente_codigo: str = ""
    representante: str = ""
    bairro_destino: str = ""
    cidade_destino: str = ""
    cep_destino: str = ""
    rota_logistica: str = ""
    peso_kg: float = 0.0
    sequencia_lifo: str = ""
    is_spyder: str = "NAO"
    is_dimensao_longa: str = "NAO"
    enriquecido_mestre: str = "NAO"


class RotaVeiculoSchema(BaseModel):
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


class RoteirizacaoSchema(BaseModel):
    session_id: str
    rotas: list[RotaVeiculoSchema]
    itens_por_veiculo: dict[str, list[ItemRotaSchema]]
    backlog: list[dict[str, str]]
    coletas: list[dict[str, str]] = Field(default_factory=list)
    jornada_maxima_minutos: int = 600


class MoverPedidoSchema(BaseModel):
    numero_pedido: str
    destino: str
    motivo: str = ""
    forcar: bool = False


class MoverPedidoResponseSchema(BaseModel):
    ok: bool
    warning: str = ""
    roteirizacao: RoteirizacaoSchema


class HealthSchema(BaseModel):
    status: str = "ok"
    version: str = "3.0.0-fase3"
