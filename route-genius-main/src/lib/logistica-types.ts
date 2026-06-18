/** Tipos espelhando api/schemas.py */

export interface PedidoConsolidado {
  numero_pedido: string;
  numero_pedido_norm: string;
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
  avisos: string;
  erros: string;
}

export interface UploadResponse {
  session_id: string;
  files_saved: string[];
  warnings: string[];
}

export interface IngestaoResponse {
  session_id: string;
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

export interface ItemRota {
  numero_pedido: string;
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
  retorno_previsto: string;
  qtd_paradas: string;
  pedidos_csv: string;
}

export interface Roteirizacao {
  session_id: string;
  rotas: RotaVeiculo[];
  itens_por_veiculo: Record<string, ItemRota[]>;
  backlog: Array<Record<string, string>>;
  coletas: Array<Record<string, string>>;
  jornada_maxima_minutos: number;
}

export interface MoverPedidoRequest {
  numero_pedido: string;
  destino: string;
  motivo?: string;
  forcar?: boolean;
}

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
export const COLUMN_COLETAS = "COLETAS";

export type ConsolidadoPatch = Partial<
  Pick<
    PedidoConsolidado,
    "cliente" | "bairro" | "cidade" | "cep" | "representante" | "status"
  >
>;

export const STATUS_FRETE_OPCOES = [
  { value: "LIBERADO", label: "Liberado (frota própria)" },
  { value: "RETIRA FOB", label: "Retira FOB" },
  { value: "ENTREGA_TERCEIRO_HUB", label: "Redespacho (Hub terceiro)" },
  { value: "BLOQUEIO FISCAL", label: "Bloqueio fiscal" },
] as const;

export const SESSION_KEY = "sf_logistica_session_id";
