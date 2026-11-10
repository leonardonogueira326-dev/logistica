/** Tipos espelhando api/schemas.py */

export interface PedidoConsolidado {
  numero_pedido: string;
  numero_pedido_norm: string;
  id_item?: string;
  of_ano?: string;
  numero_solicitacao?: string;
  seq_solicitacao?: string;
  ja_programado_kg?: number;
  ja_programado_info?: string;
  representante_codigo?: string;
  data_referencia?: string;
  dias_uteis_antecedencia?: number;
  /** "", LIBERADO, NAO_LIBERADO (se está pendente vem em `pendencias`) */
  consulta_representante?: string;
  consulta_obs?: string;
  consulta_em?: string;
  /** "AGUARDANDO" = pagamento antecipado esperando o comercial liberar */
  liberacao_comercial?: string;
  liberacao_comercial_por?: string;
  liberacao_comercial_em?: string;
  liberacao_comercial_obs?: string;
  transportadora?: string;
  transportadora_codigo?: string;
  frete_conferido?: string;
  frete_conferido_em?: string;
  /** Conferência linha a linha: só linha conferida vai para o Kanban */
  conferida?: string;
  conferida_em?: string;
  /** Por que virou retira/coleta (calculado no servidor) */
  evidencia_frete?: string;
  evidencia_nivel?: "VERDE" | "VERMELHO" | "";
  obs_recebimento?: string;
  /** Remessa / NF triangular: entrega física em outra empresa */
  entrega_em?: string;
  /** Remessa p/ industrialização: ida (peso 0) ou volta (com peso) */
  industrializacao?: string;
  entrega_cliente_codigo?: string;
  /** Veio de um dia anterior sem sair (data ISO do 1º dia pendente) */
  pendente_desde?: string;
  /** Calculado pela API: CONSULTA_REPRESENTANTE, PAGAMENTO_ANTECIPADO, PESO_ZERADO */
  pendencias?: Pendencia[];
  motivo_parado?: string;
  cliente: string;
  cliente_codigo: string;
  peso_kg: number;
  valor_tt: number;
  cidade: string;
  estado: string;
  bairro: string;
  cidade_destino: string;
  estado_destino: string;
  bairro_destino: string;
  cep: string;
  cep_destino: string;
  representante: string;
  rota_logistica: string;
  enriquecido_mestre: string;
  status: string;
  motivo_bloqueio: string;
  tipo_frete: string;
  is_spyder: string;
  is_dimensao_longa: string;
  exige_syder: string;
  motivo_alocacao: string;
  fontes: string;
  auditoria: string;
  observacao_comercial: string;
  data_producao: string;
  revisao_obrigatoria: string;
  motivo_quarentena: string;
  palavra_chave_quarentena: string;
  flag_revisao_llm: string;
  sugestao_llm_status: string;
  status_ia: string;
  tipo_frete_regex: string;
  hash_id?: string;
  data_prevista_recebimento?: string;
  motivo_atraso?: string;
  motivo_adiantamento?: string;
  representante_autorizou?: string;
  aceita_antecipacao?: string;
  latitude?: number | null;
  longitude?: number | null;
}

export interface ResumoIngestao {
  pedidos_pdf: string;
  retencoes_xlsb: string;
  eventos_email: string;
  consolidados: string;
  enriquecidos_mestre: string;
  cadastro_clientes: string;
  liberados: string;
  bloqueio_fiscal: string;
  travado_comercial: string;
  retira_fob: string;
  terceiros: string;
  terceiros_hub?: string;
  revisao_obrigatoria?: string;
  processando_ia?: string;
  avisos: string;
  erros: string;
}

export interface UploadResponse {
  session_id: string;
  files_saved: string[];
  warnings: string[];
  adicionado_ao_quadro?: boolean;
}

export interface IngestaoResponse {
  session_id: string;
  linhas_novas?: number;
  resumo: ResumoIngestao;
  consolidados: PedidoConsolidado[];
  avisos: string[];
  erros: string[];
}

export interface ConsolidadosList {
  session_id: string;
  validated: boolean;
  resumo: ResumoIngestao | null;
  consolidados: PedidoConsolidado[];
  avisos: string[];
}

export interface ValidacaoConfirmar {
  session_id: string;
  validated: boolean;
  total_consolidados: number;
  message: string;
  regras_salvas?: number;
}

export const COD_REVISAO_OBRIGATORIA = "REVISAO_OBRIGATORIA";
export const COD_PROCESSANDO_IA = "PROCESSANDO_IA";

const ROTULO_SUGESTAO_LLM: Record<string, string> = {
  LIBERADO: "Liberado (frota própria)",
  RETIRA_FOB: "Retira FOB",
  ENTREGA_TERCEIRO_HUB: "Redespacho (Hub terceiro)",
};

export function rotuloSugestaoLlm(status: string): string {
  return ROTULO_SUGESTAO_LLM[status] ?? status;
}

/** Chave plana para memoria_operacional.json (espelha memoria_operacional.py). */
export function montarChaveMemoriaOperacional(observacao: string, descricao = ""): string {
  const bruto = `${observacao || ""} ${descricao || ""}`.trim();
  return bruto
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

/** Monta chave plana codigo_palavra (espelha aprendizado_regras.py). */
export function montarChaveRegraAprendizado(codigoCliente: string, palavraChave: string): string {
  const cod = String(parseInt(codigoCliente, 10) || codigoCliente).trim();
  const palavra = palavraChave
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
  if (!cod || !palavra) return "";
  return `${cod}_${palavra}`;
}

export function palavraChaveParaAprendizado(row: PedidoConsolidado): string {
  if (row.palavra_chave_quarentena?.trim()) return row.palavra_chave_quarentena.trim();
  if (row.motivo_quarentena?.includes("Peso Zerado")) return "pesozero";
  const m = row.motivo_quarentena?.match(/Palavra Suspeita:\s*(.+)/i);
  return m?.[1]?.trim() ?? "";
}

/**
 * Identidade de uma carga no Kanban: pedido/ano/item + OF (ex.: 003060/26/002#008761/25).
 * O nº do pedido sozinho se repete (várias OFs por item), então nunca use ele para achar o card.
 */
export function idCarga(p: { id_carga?: string; id_item?: string; numero_pedido?: string }): string {
  return String(p.id_carga || p.id_item || p.numero_pedido || "");
}

export interface ItemRota {
  numero_pedido: string;
  id_carga?: string;
  id_item?: string;
  of_ano?: string;
  /** Horário/dia de recebimento do cliente ("SÓ ABRE AS 8:00") */
  obs_recebimento?: string;
  /** Remessa / NF triangular: entrega física em outra empresa */
  entrega_em?: string;
  entrega_cliente_codigo?: string;
  /** Veio de um dia anterior sem sair (data ISO do 1º dia pendente) */
  pendente_desde?: string;
  data_producao?: string;
  /** "1/2", "2/2"... quando a linha foi dividida entre caminhões */
  parte?: string;
  peso_total_linha?: number;
  /** "SIM" = dividida pelo sistema e ainda não conferida pelo operador */
  divisao_automatica?: string;
  cliente: string;
  cliente_codigo: string;
  representante: string;
  bairro_destino: string;
  cidade_destino: string;
  cep_destino: string;
  rota_logistica: string;
  peso_kg: number;
  sequencia_lifo: string;
  is_spyder: string;
  is_dimensao_longa: string;
  enriquecido_mestre: string;
}

export interface RotaVeiculo {
  veiculo_id: string;
  veiculo_nome: string;
  regiao_predominante: string;
  rota_vocacao: string;
  capacidade_kg: number;
  peso_alocado_kg: number;
  eficiencia_pct: string;
  tempo_total_min: string;
  teo_minutos: string;
  teo_hhmm: string;
  segunda_viagem_elegivel: boolean;
  alerta_elastico: boolean;
  mensagem_alerta_elastico: string;
  retorno_previsto: string;
  qtd_paradas: string;
  pedidos_csv: string;
}

export interface Roteirizacao {
  /** Caminhões fechados pelo operador (a sugestão não mexe) */
  veiculos_fechados?: string[];
  /** Caminhões que não saíram: a carga vai para a próxima rota */
  veiculos_nao_sairam?: string[];
  /** Motorista/ajudante/placa por caminhão no dia (vai para o romaneio) */
  equipe_por_veiculo?: Record<string, EquipeVeiculo>;
  /** Resultado da última sugestão/montagem */
  mensagem?: string;
  session_id: string;
  rotas: RotaVeiculo[];
  itens_por_veiculo: Record<string, ItemRota[]>;
  backlog: Array<Record<string, string>>;
  backlog_futuro: Array<Record<string, string>>;
  backlog_local: Array<Record<string, string>>;
  coletas: Array<Record<string, string>>;
  itens_retorno_por_veiculo: Record<string, ItemRota[]>;
  viagens_retorno_habilitadas: string[];
  metricas_retorno: Record<
    string,
    { teo_minutos: string; teo_hhmm: string; peso_alocado_kg: number; qtd_pedidos: string }
  >;
  jornada_maxima_minutos: number;
}

export interface MoverPedidoRequest {
  numero_pedido: string;
  destino: string;
  motivo?: string;
  forcar?: boolean;
  /** Card "Consultar representante" solto num caminhão: o representante liberou. */
  liberar_representante?: boolean;
  autorizado_por?: string;
}

export interface DividirCargaRequest {
  id_carga: string;
  peso_kg: number;
}

export type Pendencia = "CONSULTA_REPRESENTANTE" | "PAGAMENTO_ANTECIPADO" | "PESO_ZERADO";

export interface EquipeVeiculo {
  motorista: string;
  ajudante: string;
  placa: string;
}

export type ResultadoConsulta = "LIBERADO" | "NAO_LIBERADO" | "PENDENTE";

export interface LiberacaoComercialRequest {
  ids: string[];
  resultado: "LIBERADO" | "AGUARDANDO";
  liberado_por?: string;
  obs?: string;
}

export interface ConsultaRepresentanteRequest {
  ids: string[];
  resultado: ResultadoConsulta;
  autorizado_por?: string;
  obs?: string;
}

export interface ConsultaRepresentanteResponse {
  ok: boolean;
  atualizados: number;
  message: string;
  alocados: Record<string, string>;
}

export interface AjustarDivisaoRequest {
  id_carga: string;
  peso_kg: number;
  id_carga_contrapartida?: string;
}

export type OperacaoDivisao =
  | { op: "dividir"; body: DividirCargaRequest }
  | { op: "ajustar"; body: AjustarDivisaoRequest }
  | { op: "juntar"; body: { id_carga: string } }
  | { op: "confirmar"; body: { id_carga: string } };

export interface MoverPedidoResponse {
  ok: boolean;
  warning: string;
  roteirizacao: Roteirizacao;
}

export const MOTIVOS_BACKLOG = [
  "FROTA INSUFICIENTE",
  "LIMITE DE JORNADA ATINGIDO",
  "DECISAO OPERADOR",
  "BLOQUEIO FISCAL",
  "TRAVADO COMERCIAL",
] as const;

export const COLUMN_BACKLOG = "BACKLOG";
export const COLUMN_BACKLOG_FUTURO = "BACKLOG_FUTURO";
export const COLUMN_BACKLOG_LOCAL = "BACKLOG_LOCAL";
export const COLUMN_COLETAS = "COLETAS";
export const SUFIXO_VIAGEM_RETORNO = "::RETORNO";
export const TEO_ALERTA_MIN = 510;
export const TEO_SEGUNDA_VIAGEM_MAX_MIN = 360;

export function idRetornoVeiculo(veiculoId: string): string {
  return `${veiculoId}${SUFIXO_VIAGEM_RETORNO}`;
}

export function parseRetornoVeiculo(columnId: string): string | null {
  if (!columnId.endsWith(SUFIXO_VIAGEM_RETORNO)) return null;
  return columnId.slice(0, -SUFIXO_VIAGEM_RETORNO.length);
}

export type ConsolidadoPatch = Partial<
  Pick<
    PedidoConsolidado,
    "cliente" | "bairro" | "cidade" | "cep" | "representante" | "status"
  >
>;

export const STATUS_FRETE_OPCOES = [
  { value: "LIBERADO", label: "Liberado (frota própria)" },
  { value: "ENTREGA_TERCEIRO_HUB", label: "Levar na transportadora" },
  { value: "TERCEIRO", label: "Transportadora coleta" },
  { value: "RETIRA FOB", label: "Cliente retira (FOB)" },
  { value: "BLOQUEIO FISCAL", label: "Bloqueio fiscal" },
] as const;

export const SESSION_KEY = "sf_logistica_session_id";

export interface VeiculoSetup {
  id: string;
  placa: string;
  nome: string;
  capacidade_kg: number;
  tipo: string;
  ativo: boolean;
  reserva: boolean;
}

export interface PessoaEquipe {
  nome: string;
  cnh?: string;
  telefone?: string;
}

export interface RotaSetup {
  cidade: string;
  rota_logistica: string;
  macro_regiao: string;
  tempo_medio_viagem_min: number;
}

export interface ConfiguracaoOperacional {
  _versao?: string;
  _descricao?: string;
  frota: VeiculoSetup[];
  equipe: { motoristas: PessoaEquipe[]; ajudantes: PessoaEquipe[] };
  rotas: RotaSetup[];
  horarios: {
    inicio_expediente: string;
    limite_retorno: string;
    tempo_descarga_minutos: number;
    tempo_almoco_minutos: number;
    jornada_maxima_minutos: number;
    velocidade_media_kmh: number;
    turnos: Array<{ nome: string; saida: string; fim: string }>;
  };
  operacao: {
    peso_max_spyder_no_bau_kg: number;
    permitir_spyder_no_bau: boolean;
    comprimentos_longos_mm: string;
    rotas_vizinhas: Record<string, string>;
    motivos_backlog: string;
    cadastro_clientes_path: string;
  };
}

export interface SetupResponse {
  config: ConfiguracaoOperacional;
  arquivo: string;
}

export interface ConfigResponse {
  config: ConfiguracaoOperacional;
  arquivo: string;
  message: string;
}

export interface HistoricoRegistro {
  hash_id: string;
  numero_pedido: string;
  numero_pedido_norm: string;
  cliente: string;
  cliente_codigo: string;
  status_final: string;
  data_entrega: string;
  data_arquivamento: string;
  session_id: string;
  arquivo_historico: string;
}

export interface HistoricoResponse {
  q: string;
  total: number;
  resultados: HistoricoRegistro[];
}

export interface AnteciparPedidoBody {
  numero_pedido: string;
  motivo_adiantamento: string;
  representante_autorizou?: string;
}

export interface AnteciparPedidoResponse {
  ok: boolean;
  session_id: string;
  numero_pedido: string;
  destino: string;
  message: string;
  roteirizacao: Roteirizacao;
}

export interface PedidoManualBody {
  session_id: string;
  numero_pedido: string;
  cliente: string;
  cliente_codigo?: string;
  peso_kg?: number;
  valor_tt?: number;
  cidade?: string;
  bairro?: string;
  cep?: string;
  representante?: string;
  observacao_comercial?: string;
  status?: string;
  data_prevista_recebimento?: string;
  motivo_atraso?: string;
}
