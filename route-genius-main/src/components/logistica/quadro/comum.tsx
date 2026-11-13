import { pointerWithin, rectIntersection, type CollisionDetection } from "@dnd-kit/core";
import { Clock, Inbox, MapPin, PackageSearch, PhoneCall, Truck } from "lucide-react";

import { type CardPedido } from "@/components/logistica/PedidoKanbanCard";
import {
  COLUMN_BACKLOG,
  COLUMN_BACKLOG_FUTURO,
  COLUMN_BACKLOG_LOCAL,
  COLUMN_COLETAS,
  SUFIXO_VIAGEM_RETORNO,
  TEO_ALERTA_MIN,
} from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

export type PendingMove = {
  /** Uma ou várias cargas (seleção múltipla / parada inteira) */
  ids: string[];
  origem: string;
  destino: string;
  forcar?: boolean;
  liberarRepresentante?: boolean;
  autorizadoPor?: string;
  transportadoraCodigo?: string;
};

export type MoverLoteFn = (payload: {
  ids: string[];
  destino: string;
  motivo?: string;
  forcar?: boolean;
  liberar_representante?: boolean;
  autorizado_por?: string;
  transportadora_codigo?: string;
}) => Promise<void>;

export const pendenciasDoCard = (p: CardPedido): string[] =>
  String((p as Record<string, string>).pendencias ?? "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

/** Levar na transportadora com "TRANSPORTADORA A DEFINIR": o representante ainda vai dizer qual. */
export const transportadoraADefinir = (p: CardPedido) => {
  const raw = p as Record<string, string>;
  return (
    /\bA\s+(DEFINIR|COMBINAR|CONFIRMAR)\b/i.test(String(raw.transportadora ?? "")) ||
    /transportadora a definir/i.test(String(raw.motivo ?? ""))
  );
};

/** Comercial e peso zerado não sobem no caminhão: ficam na página Pendências. */
export const cardTravado = (p: CardPedido) =>
  pendenciasDoCard(p).some((x) => x === "PAGAMENTO_ANTECIPADO" || x === "PESO_ZERADO");

export const COLUNAS_NAO_VEICULO = new Set([
  COLUMN_BACKLOG,
  COLUMN_BACKLOG_FUTURO,
  COLUMN_BACKLOG_LOCAL,
  COLUMN_COLETAS,
]);

export type AcoesDivisao = {
  dividir: (p: CardPedido) => void;
  ajustar: (p: CardPedido) => void;
  juntar: (p: CardPedido) => void;
  confirmar: (p: CardPedido) => void;
};

export function formatTeoMin(min: number) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}h${m.toString().padStart(2, "0")}`;
}

export function TeoBadge({ teoMin, teoLabel }: { teoMin: number; teoLabel: string }) {
  const alerta = teoMin > TEO_ALERTA_MIN;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold font-mono",
        alerta
          ? "bg-destructive/15 text-destructive border border-destructive/40"
          : "bg-muted text-muted-foreground border border-border",
      )}
      title={alerta ? "TEO acima de 8h30 — alerta de jornada" : "Tempo Estimado de Operação"}
    >
      <Clock className="w-3 h-3" />
      {teoLabel}
    </span>
  );
}

/** Prefere a área da 2ª viagem quando o ponteiro está sobre ela (fica dentro do card do caminhão). */
export const colisao: CollisionDetection = (args) => {
  const sob = pointerWithin(args);
  if (sob.length) {
    const retorno = sob.find((c) => String(c.id).endsWith(SUFIXO_VIAGEM_RETORNO));
    return retorno ? [retorno] : sob;
  }
  return rectIntersection(args);
};

export const ABAS_ALOCAR: { id: string; label: string; icon: typeof Truck }[] = [
  { id: COLUMN_BACKLOG, label: "Fila", icon: Inbox },
  { id: COLUMN_BACKLOG_FUTURO, label: "Representante", icon: PhoneCall },
  { id: COLUMN_BACKLOG_LOCAL, label: "Locais", icon: MapPin },
  { id: COLUMN_COLETAS, label: "Coletas", icon: PackageSearch },
];

export type PropsCardFn = (id: string) => {
  selecionado: boolean;
  onSelecionar: () => void;
  destaque?: "achou" | "apagado";
  idsArrasto: string[];
};

export const divisaoDoCard = (onDivisao: AcoesDivisao | undefined, pedido: CardPedido) =>
  onDivisao
    ? {
        dividir: () => onDivisao.dividir(pedido),
        ajustar: () => onDivisao.ajustar(pedido),
        juntar: () => onDivisao.juntar(pedido),
        confirmar: () => onDivisao.confirmar(pedido),
      }
    : undefined;
