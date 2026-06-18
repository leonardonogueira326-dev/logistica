import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, MoreHorizontal } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ItemRota } from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

export type CardPedido = ItemRota | Record<string, string>;

export function getCardId(p: CardPedido) {
  return String(p.numero_pedido ?? "");
}

export function PedidoKanbanCard({
  pedido,
  columnId,
  destinos,
  onMoveTo,
  onOpenAudit,
  dragging,
}: {
  pedido: CardPedido;
  columnId: string;
  destinos: { id: string; label: string }[];
  onMoveTo: (destino: string) => void;
  onOpenAudit?: (numeroPedido: string) => void;
  dragging?: boolean;
}) {
  const id = getCardId(pedido);
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `${columnId}::${id}`,
    data: { pedido, columnId, numeroPedido: id },
  });

  const style = transform
    ? { transform: CSS.Translate.toString(transform) }
    : undefined;

  const cliente = String(pedido.cliente ?? "");
  const bairro = String(pedido.bairro_destino ?? "");
  const cidade = String(pedido.cidade_destino ?? "");
  const peso = Number(pedido.peso_kg ?? 0);
  const isSpyder = pedido.is_spyder === "SIM";
  const isLonga = pedido.is_dimensao_longa === "SIM";

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "rounded-lg border border-border bg-card shadow-sm text-sm transition-shadow hover:shadow-md",
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
          <div className="font-medium truncate">{cliente}</div>
          <div className="text-xs text-muted-foreground truncate mt-0.5">
            {bairro}
            {bairro && cidade ? ", " : ""}
            {cidade}
          </div>
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
