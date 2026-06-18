import { Progress } from "@/components/ui/progress";
import type { RotaVeiculo } from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

export function VehicleMetrics({
  rota,
  jornadaMax,
}: {
  rota: RotaVeiculo;
  jornadaMax: number;
}) {
  const pesoPct = pct(rota.capacidade_kg, rota.peso_alocado_kg);
  const tempoMin = parseInt(rota.tempo_total_min, 10) || 0;
  const jornadaPct = jornadaMax ? Math.min(100, Math.round((tempoMin / jornadaMax) * 100)) : 0;

  return (
    <div className="space-y-2 px-3 pb-3">
      <MetricBar
        label={`Peso · ${rota.peso_alocado_kg.toLocaleString("pt-BR")} / ${rota.capacidade_kg.toLocaleString("pt-BR")} kg`}
        pct={pesoPct}
      />
      <MetricBar
        label={`Jornada · ${formatMin(tempoMin)} / ${formatMin(jornadaMax)} · ${rota.qtd_paradas} paradas`}
        pct={jornadaPct}
      />
    </div>
  );
}

function pct(cap: number, used: number) {
  return cap ? Math.min(100, Math.round((used / cap) * 100)) : 0;
}

function barColor(pct: number) {
  if (pct >= 90) return "[&>div]:bg-destructive";
  if (pct >= 70) return "[&>div]:bg-warning";
  return "[&>div]:bg-success";
}

function MetricBar({ label, pct }: { label: string; pct: number }) {
  return (
    <div>
      <div className="flex justify-between text-[10px] text-muted-foreground mb-1">
        <span className="truncate pr-2">{label}</span>
        <span className="font-mono font-semibold shrink-0">{pct}%</span>
      </div>
      <Progress value={pct} className={cn("h-1.5", barColor(pct))} />
    </div>
  );
}

function formatMin(min: number) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}h${m.toString().padStart(2, "0")}`;
}

export function VehicleMetricsCompact({
  rota,
  jornadaMax,
}: {
  rota: RotaVeiculo;
  jornadaMax: number;
}) {
  const pesoPct = pct(rota.capacidade_kg, rota.peso_alocado_kg);
  const tempoMin = parseInt(rota.tempo_total_min, 10) || 0;
  const jornadaPct = jornadaMax ? Math.min(100, Math.round((tempoMin / jornadaMax) * 100)) : 0;

  return (
    <div className="space-y-2 mt-3">
      <Progress value={pesoPct} className={cn("h-1.5", barColor(pesoPct))} />
      <Progress value={jornadaPct} className={cn("h-1.5", barColor(jornadaPct))} />
    </div>
  );
}
