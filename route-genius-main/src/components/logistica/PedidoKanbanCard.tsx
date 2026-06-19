import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { Crosshair, GripVertical, MoreHorizontal } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ItemRota } from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

export type CardPedido = ItemRota | Record<string, string>;

export function getCardId(p: CardPedido) {
  return String(p.numero_pedido ?? "");
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
  variant = "default",
  dragging,
}: {
  pedido: CardPedido;
  columnId: string;
  destinos: { id: string; label: string }[];
  onMoveTo: (destino: string) => void;
  onOpenAudit?: (numeroPedido: string) => void;
  onAntecipar?: (numeroPedido: string) => void;
  variant?: "default" | "futuro";
  dragging?: boolean;
}) {
  const id = getCardId(pedido);
  const raw = pedido as Record<string, string>;
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `${columnId}::${id}`,
    data: { pedido, columnId, numeroPedido: id },
  });

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

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "rounded-lg border shadow-sm text-sm transition-shadow hover:shadow-md",
        isFuturo
          ? "border-muted-foreground/25 bg-muted/40 opacity-90"
          : "border-border bg-card",
        (isDragging || dragging) && "opacity-50 ring-2 ring-accent",
      )}
    >
      <div className="flex items-start gap-1.5 p-3">
        <button
          type="button"
          className="mt-0.5 text-muted-foreground hover:text-foreground cursor-grab active:cursor-grabbing shrink-0 touch-none"
          {...listeners}
          {...attributes}
          onClick={(e) => e.stopPropagation()}
        >
          <GripVertical className="w-4 h-4" />
        </button>

        <button
          type="button"
          className="flex-1 min-w-0 text-left"
          onClick={() => onOpenAudit?.(id)}
        >
          <div className="flex items-center gap-1.5 flex-wrap">
            <div className="font-medium truncate">{cliente}</div>
            {isFuturo && dataPrev && (
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-5 font-normal">
                Data: {formatDataBadge(dataPrev)}
              </Badge>
            )}
          </div>
          <div className="text-xs text-muted-foreground truncate mt-0.5">
            {bairro}
            {bairro && cidade ? ", " : ""}
            {cidade}
          </div>
          {oportunidade && oportunidadeDica && (
            <div className="mt-2 flex items-start gap-1.5 text-[11px] text-accent bg-accent/10 border border-accent/30 rounded px-2 py-1">
              <Crosshair className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{oportunidadeDica}</span>
            </div>
          )}
          <div className="mt-2 flex items-end justify-between gap-2">
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
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-5 text-muted-foreground">
                  Backlog Futuro
                </Badge>
              )}
            </div>
            <span className="font-bold font-mono text-sm shrink-0">
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
            <DropdownMenuItem onClick={() => onOpenAudit?.(id)}>
              Ver auditoria
            </DropdownMenuItem>
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
