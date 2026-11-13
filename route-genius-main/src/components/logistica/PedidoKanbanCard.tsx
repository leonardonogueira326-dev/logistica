import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { Clock, Crosshair, GripVertical, MapPinOff, MoreHorizontal, Truck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { idCarga, type ItemRota } from "@/lib/logistica-types";
import { cn } from "@/lib/utils";
import { textoPendenteDesde } from "@/lib/mensagens";
import { apelido as apelidoCliente } from "@/lib/montagem";

export type CardPedido = ItemRota | Record<string, string>;

export function getCardId(p: CardPedido) {
  return idCarga(p as { id_carga?: string; id_item?: string; numero_pedido?: string });
}

function formatDataBadge(iso: string): string {
  if (!iso) return "";
  const parts = iso.split("-");
  if (parts.length === 3) return `${parts[2]}/${parts[1]}`;
  return iso;
}

export function PedidoKanbanCard({
  pedido,
  columnId,
  destinos,
  onMoveTo,
  onOpenAudit,
  onAntecipar,
  onDivisao,
  variant = "default",
  dragging,
  parada,
  cor,
  selecionado,
  onSelecionar,
  destaque,
  semLocal,
  idsArrasto,
  compacto,
}: {
  pedido: CardPedido;
  columnId: string;
  destinos: { id: string; label: string }[];
  onMoveTo: (destino: string) => void;
  onOpenAudit?: (numeroPedido: string) => void;
  onAntecipar?: (numeroPedido: string) => void;
  onDivisao?: {
    dividir: () => void;
    ajustar: () => void;
    juntar: () => void;
    confirmar: () => void;
  };
  variant?: "default" | "futuro" | "local" | "retorno";
  dragging?: boolean;
  /** Nº da parada no caminhão (ordem de entrega) */
  parada?: number;
  /** Cor do caminhão (a mesma do mapa) */
  cor?: string;
  selecionado?: boolean;
  /** Marca/desmarca na seleção múltipla */
  onSelecionar?: () => void;
  /** Busca: "achou" destaca, "apagado" esmaece */
  destaque?: "achou" | "apagado";
  semLocal?: boolean;
  /** O que vai junto quando arrastar este card (seleção múltipla) */
  idsArrasto?: string[];
  /** Dentro de uma parada com várias linhas: sem repetir cliente e endereço */
  compacto?: boolean;
}) {
  const id = getCardId(pedido);
  const raw = pedido as Record<string, string>;
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `${columnId}::${id}`,
    data: {
      pedido,
      columnId,
      numeroPedido: id,
      ids: idsArrasto && idsArrasto.length ? idsArrasto : [id],
    },
  });
  const nomeCurto = apelidoCliente(String(pedido.cliente ?? ""));

  const style = transform ? { transform: CSS.Translate.toString(transform) } : undefined;

  const cliente = String(pedido.cliente ?? "");
  const bairro = String(pedido.bairro_destino ?? "");
  const cidade = String(pedido.cidade_destino ?? "");
  const peso = Number(pedido.peso_kg ?? 0);
  const isSpyder = pedido.is_spyder === "SIM";
  const isLonga = pedido.is_dimensao_longa === "SIM";
  const dataPrev = raw.data_prevista_recebimento ?? "";
  const oportunidade = raw.oportunidade === "SIM";
  const oportunidadeDica = raw.oportunidade_dica ?? "";
  const isFuturo = variant === "futuro";
  const numeroPedido = String(pedido.numero_pedido ?? "");
  const parte = String(raw.parte ?? "");
  const pesoTotalLinha = Number(raw.peso_total_linha ?? 0);
  const divisaoAutomatica = raw.divisao_automatica === "SIM";
  const of = String(raw.of_ano ?? "");

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-card-id={id}
      className={cn(
        "rounded-lg border shadow-sm text-sm transition-[box-shadow,opacity] hover:shadow-md",
        isFuturo ? "border-muted-foreground/25 bg-muted/40 opacity-90" : "border-border bg-card",
        compacto && "shadow-none",
        selecionado && "ring-2 ring-accent border-accent bg-accent/5",
        destaque === "achou" && "ring-2 ring-amber-400 bg-amber-50",
        destaque === "apagado" && "opacity-35",
        (isDragging || dragging) && "opacity-50 ring-2 ring-accent",
      )}
    >
      <div className={cn("flex items-start gap-1.5", compacto ? "px-2 py-1.5" : "p-2.5")}>
        <div className="flex flex-col items-center gap-1 shrink-0">
          <button
            type="button"
            title="Arrastar (se houver cards selecionados, vão todos juntos)"
            className="mt-0.5 text-muted-foreground hover:text-foreground cursor-grab active:cursor-grabbing touch-none"
            {...listeners}
            {...attributes}
            onClick={(e) => e.stopPropagation()}
          >
            <GripVertical className="w-4 h-4" />
          </button>
          {onSelecionar && (
            <input
              type="checkbox"
              aria-label="Selecionar"
              title="Selecionar (Ctrl+clique no card também seleciona)"
              className="h-3.5 w-3.5 cursor-pointer accent-[var(--color-accent,#2563eb)]"
              checked={!!selecionado}
              onChange={onSelecionar}
              onClick={(e) => e.stopPropagation()}
            />
          )}
        </div>

        <button
          type="button"
          className="flex-1 min-w-0 text-left"
          onClick={(e) => {
            if ((e.ctrlKey || e.metaKey || e.shiftKey) && onSelecionar) {
              e.preventDefault();
              onSelecionar();
              return;
            }
            onOpenAudit?.(id);
          }}
        >
          {!compacto && (
            <>
              <div className="flex items-center gap-1.5">
                {parada !== undefined && (
                  <span
                    className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full px-1 text-[11px] font-bold text-white"
                    style={{ background: cor ?? "#64748b" }}
                    title={`${parada}ª entrega`}
                  >
                    {parada}
                  </span>
                )}
                <div className="font-semibold truncate" title={cliente}>
                  {nomeCurto || cliente}
                </div>
                {isFuturo && dataPrev && (
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-5 font-normal">
                    Data: {formatDataBadge(dataPrev)}
                  </Badge>
                )}
              </div>
              <div
                className="text-xs text-muted-foreground truncate mt-0.5"
                title={`${cliente} — ${bairro} ${cidade}`}
              >
                {bairro}
                {bairro && cidade ? ", " : ""}
                {cidade}
              </div>
              {semLocal && (
                <div className="mt-1 inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-amber-800">
                  <MapPinOff className="w-3 h-3" /> Sem localização no mapa
                </div>
              )}
            </>
          )}
          {raw.pendente_desde && (
            <div className="mt-1 inline-flex items-center gap-1 rounded bg-rose-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-rose-700">
              <Clock className="w-3 h-3" /> {textoPendenteDesde(raw.pendente_desde)}
            </div>
          )}
          {raw.entrega_em && !compacto && (
            <div
              className="mt-1 flex items-start gap-1 rounded bg-violet-500/10 px-1.5 py-0.5 text-[11px] font-medium text-violet-700"
              title="Remessa: o material vai para outra empresa (veja a observação do pedido)"
            >
              <Truck className="w-3 h-3 shrink-0 mt-0.5" />
              <span className="line-clamp-2">Entregar em: {raw.entrega_em}</span>
            </div>
          )}
          {raw.obs_recebimento && !compacto && (
            <div
              className="mt-1 flex items-start gap-1 text-[11px] text-sky-700"
              title={raw.obs_recebimento}
            >
              <Clock className="w-3 h-3 shrink-0 mt-0.5" />
              <span className="line-clamp-2">{raw.obs_recebimento}</span>
            </div>
          )}
          {numeroPedido && (
            <div className="text-[11px] font-mono text-muted-foreground truncate mt-0.5">
              {numeroPedido}
              {of && <span className="text-foreground/70"> · OF {of}</span>}
            </div>
          )}
          {isFuturo && raw.motivo && (
            <div className="mt-2 text-[11px] text-amber-700 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1">
              {raw.motivo}
            </div>
          )}
          {oportunidade && oportunidadeDica && (
            <div className="mt-2 flex items-start gap-1.5 text-[11px] text-accent bg-accent/10 border border-accent/30 rounded px-2 py-1">
              <Crosshair className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{oportunidadeDica}</span>
            </div>
          )}
          <div className={cn("flex items-end justify-between gap-2", compacto ? "mt-0.5" : "mt-2")}>
            <div className="flex flex-wrap gap-1">
              {isSpyder && (
                <Badge variant="destructive" className="text-[10px] px-1.5 py-0 h-5">
                  SPYDER
                </Badge>
              )}
              {isLonga && (
                <Badge variant="destructive" className="text-[10px] px-1.5 py-0 h-5">
                  LONGA
                </Badge>
              )}
              {isFuturo && (
                <Badge
                  variant="outline"
                  className="text-[10px] px-1.5 py-0 h-5 text-muted-foreground"
                >
                  {raw.pendencias ? "Parado" : "Data futura"}
                </Badge>
              )}
              {divisaoAutomatica && (
                <Badge className="text-[10px] px-1.5 py-0 h-5 bg-amber-500/15 text-amber-700 border border-amber-500/40 hover:bg-amber-500/15">
                  Divisão automática — conferir
                </Badge>
              )}
              {parte && (
                <Badge
                  variant="outline"
                  className="text-[10px] px-1.5 py-0 h-5 border-accent/50 text-accent"
                  title={
                    pesoTotalLinha
                      ? `Linha total: ${pesoTotalLinha.toLocaleString("pt-BR")} kg`
                      : undefined
                  }
                >
                  Parte {parte}
                  {pesoTotalLinha ? ` · de ${pesoTotalLinha.toLocaleString("pt-BR")} kg` : ""}
                </Badge>
              )}
            </div>
            <span className={cn("font-bold font-mono shrink-0", compacto ? "text-xs" : "text-sm")}>
              {peso.toLocaleString("pt-BR")} kg
            </span>
          </div>
        </button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="p-1 rounded hover:bg-muted shrink-0"
              onClick={(e) => e.stopPropagation()}
            >
              <MoreHorizontal className="w-4 h-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {isFuturo && onAntecipar && (
              <>
                <DropdownMenuItem onClick={() => onAntecipar(id)}>
                  Antecipar Entrega / Adicionar à Rota
                </DropdownMenuItem>
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuItem onClick={() => onOpenAudit?.(id)}>Ver auditoria</DropdownMenuItem>
            {onDivisao && (
              <>
                <DropdownMenuSeparator />
                {peso > 1 && (
                  <DropdownMenuItem onClick={onDivisao.dividir}>Dividir carga…</DropdownMenuItem>
                )}
                {parte && (
                  <DropdownMenuItem onClick={onDivisao.ajustar}>Ajustar divisão…</DropdownMenuItem>
                )}
                {parte && (
                  <DropdownMenuItem onClick={onDivisao.juntar}>Juntar partes</DropdownMenuItem>
                )}
                {divisaoAutomatica && (
                  <DropdownMenuItem onClick={onDivisao.confirmar}>
                    Confirmar divisão
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
              </>
            )}
            {destinos
              .filter((d) => d.id !== columnId)
              .map((d) => (
                <DropdownMenuItem key={d.id} onClick={() => onMoveTo(d.id)}>
                  Mover para {d.label}
                </DropdownMenuItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
