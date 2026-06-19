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
    flag_revisao_llm: str = "NAO"
    sugestao_llm_status: str = ""
    status_ia: str = "NAO_APLICAVEL"
    tipo_frete_regex: str = ""
    hash_id: str = ""
    data_prevista_recebimento: str = ""
    motivo_atraso: str = ""
    fonte_entrada: str = "PDF"
    motivo_adiantamento: str = ""
    representante_autorizou: str = ""
    aceita_antecipacao: str = "SIM"


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
    processando_ia: str = "0"
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
    memoria_novas: dict[str, str] = Field(default_factory=dict)


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
    backlog_futuro: list[dict[str, str]] = Field(default_factory=list)
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
    version: str = "4.0.0-fase4"


class VeiculoSetupSchema(BaseModel):
    id: str
    placa: str = ""
    nome: str = ""
    capacidade_kg: float = 0.0
    tipo: str = "BAU"
    ativo: bool = False
    reserva: bool = False


class PessoaEquipeSchema(BaseModel):
    nome: str
    cnh: str = ""
    telefone: str = ""


class EquipeSetupSchema(BaseModel):
    motoristas: list[PessoaEquipeSchema] = Field(default_factory=list)
    ajudantes: list[PessoaEquipeSchema] = Field(default_factory=list)


class RotaSetupSchema(BaseModel):
    cidade: str
    rota_logistica: str
    macro_regiao: str = "OUTROS"
    tempo_medio_viagem_min: int = 300


class TurnoSchema(BaseModel):
    nome: str = "Expediente"
    saida: str = "07:00"
    fim: str = "17:00"


class HorariosSetupSchema(BaseModel):
    inicio_expediente: str = "07:00"
    limite_retorno: str = "17:00"
    tempo_descarga_minutos: int = 20
    tempo_almoco_minutos: int = 60
    jornada_maxima_minutos: int = 600
    velocidade_media_kmh: int = 42
    turnos: list[TurnoSchema] = Field(default_factory=list)


class OperacaoSetupSchema(BaseModel):
    peso_max_spyder_no_bau_kg: float = 800.0
    permitir_spyder_no_bau: bool = True
    comprimentos_longos_mm: str = "4800, 5900"
    rotas_vizinhas: dict[str, str] = Field(default_factory=dict)
    motivos_backlog: str = ""
    cadastro_clientes_path: str = ""


class ConfiguracaoOperacionalSchema(BaseModel):
    _versao: str = "1"
    _descricao: str = ""
    frota: list[VeiculoSetupSchema] = Field(default_factory=list)
    equipe: EquipeSetupSchema = Field(default_factory=EquipeSetupSchema)
    rotas: list[RotaSetupSchema] = Field(default_factory=list)
    horarios: HorariosSetupSchema = Field(default_factory=HorariosSetupSchema)
    operacao: OperacaoSetupSchema = Field(default_factory=OperacaoSetupSchema)


class SetupResponseSchema(BaseModel):
    config: dict[str, Any]
    arquivo: str = ""


class ConfigResponseSchema(BaseModel):
    config: dict[str, Any]
    arquivo: str = ""
    message: str = ""


class HistoricoRegistroSchema(BaseModel):
    hash_id: str = ""
    numero_pedido: str = ""
    numero_pedido_norm: str = ""
    cliente: str = ""
    cliente_codigo: str = ""
    status_final: str = ""
    data_entrega: str = ""
    data_arquivamento: str = ""
    session_id: str = ""
    arquivo_historico: str = ""


class HistoricoResponseSchema(BaseModel):
    q: str
    total: int
    resultados: list[HistoricoRegistroSchema]


class PedidoManualBodySchema(BaseModel):
    session_id: str
    numero_pedido: str
    cliente: str
    cliente_codigo: str = ""
    peso_kg: float = 0.0
    valor_tt: float = 0.0
    cidade: str = ""
    bairro: str = ""
    cep: str = ""
    representante: str = "NÃO IDENTIFICADO"
    observacao_comercial: str = ""
    status: str = "LIBERADO"
    data_prevista_recebimento: str = ""
    motivo_atraso: str = ""


class PedidoManualResponseSchema(BaseModel):
    ok: bool
    session_id: str
    numero_pedido: str
    hash_id: str = ""
    message: str = ""
    ignorado_duplicata: bool = False


class AnteciparPedidoBodySchema(BaseModel):
    numero_pedido: str
    motivo_adiantamento: str
    representante_autorizou: str = ""


class AnteciparPedidoResponseSchema(BaseModel):
    ok: bool
    session_id: str
    numero_pedido: str
    destino: str = ""
    message: str = ""
    roteirizacao: Optional["RoteirizacaoSchema"] = None
