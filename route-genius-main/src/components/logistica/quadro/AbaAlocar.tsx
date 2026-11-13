import { useDroppable } from "@dnd-kit/core";
import { Truck } from "lucide-react";

import { cn } from "@/lib/utils";

/** Aba de "A alocar" — também aceita card solto em cima dela. */
export function AbaAlocar({
  id,
  label,
  icon: Icon,
  qtd,
  achados,
  ativa,
  onClick,
}: {
  id: string;
  label: string;
  icon: typeof Truck;
  qtd: number;
  achados: number;
  ativa: boolean;
  onClick: () => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `${id}::aba`, data: { columnId: id } });
  return (
    <button
      ref={setNodeRef}
      type="button"
      onClick={onClick}
      className={cn(
        "relative flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs",
        ativa ? "border-accent bg-accent/10 font-semibold text-accent" : "hover:bg-muted",
        isOver && "ring-2 ring-accent",
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{label}</span>
      <span className="ml-auto font-mono text-[11px] text-muted-foreground">{qtd}</span>
      {achados > 0 && !ativa && (
        <span
          className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-amber-400"
          title={`${achados} achado(s) na busca`}
        />
      )}
    </button>
  );
}
