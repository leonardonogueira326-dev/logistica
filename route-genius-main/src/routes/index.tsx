import { createFileRoute } from "@tanstack/react-router";
import { Loader2, Package, Truck, TrendingUp } from "lucide-react";

import { VehicleMetricsCompact } from "@/components/logistica/VehicleMetrics";
import {
  getStoredSessionId,
  useLogisticaSession,
} from "@/hooks/useLogisticaSession";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Resumo Executivo · Roteirização SF" },
      { name: "description", content: "Visão executiva da operação logística do dia." },
    ],
  }),
  component: ResumoExecutivo,
});

function ResumoExecutivo() {
  const sessionId = getStoredSessionId();
  const { consolidadosQuery, roteirizacaoQuery } = useLogisticaSession(sessionId);

  if (!sessionId) {
    return (
      <div className="p-6">
        <div className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
          Nenhuma sessão ativa. Faça upload em{" "}
          <a href="/upload" className="font-semibold text-accent underline">
            Upload & Processamento
          </a>
          .
        </div>
      </div>
    );
  }

  const loading = consolidadosQuery.isLoading || roteirizacaoQuery.isLoading;
  const consolidados = consolidadosQuery.data;
  const roteirizacao = roteirizacaoQuery.data;

  const liberados = consolidados?.resumo?.liberados ?? "0";
  const totalConsolidados = consolidados?.consolidados.length ?? 0;
  const alocados = roteirizacao
    ? Object.values(roteirizacao.itens_por_veiculo).reduce((s, arr) => s + arr.length, 0)
    : 0;
  const pesoAlocado = roteirizacao
    ? roteirizacao.rotas.reduce((s, r) => s + r.peso_alocado_kg, 0)
    : 0;
  const jornadaMax = roteirizacao?.jornada_maxima_minutos ?? 600;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Resumo Executivo</h1>
        <p className="text-sm text-muted-foreground">Dados reais da sessão ativa</p>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Carregando KPIs…
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <KpiCard icon={TrendingUp} label="Pedidos Liberados" value={liberados} hint={`de ${totalConsolidados} consolidados`} />
        <KpiCard icon={Package} label="Alocados na Frota" value={String(alocados)} hint={`${pesoAlocado.toLocaleString("pt-BR")} kg`} />
        <KpiCard icon={Truck} label="Caminhões Ativos" value={String(roteirizacao?.rotas.length ?? 0)} hint="com carga ou disponíveis" />
        <KpiCard icon={Package} label="Backlog" value={String(roteirizacao?.backlog.length ?? 0)} hint="aguardando decisão" />
      </div>

      {roteirizacao && roteirizacao.rotas.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Frota · Peso e Jornada
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {roteirizacao.rotas.map((r) => {
              const pesoPct = r.capacidade_kg
                ? Math.round((r.peso_alocado_kg / r.capacidade_kg) * 100)
                : 0;
              const tempoMin = parseInt(r.tempo_total_min, 10) || 0;
              const jornadaPct = Math.round((tempoMin / jornadaMax) * 100);
              const warn = jornadaPct >= 85 || pesoPct >= 85;
              return (
                <div
                  key={r.veiculo_id}
                  className={cn(
                    "bg-card rounded-xl border border-border p-5 shadow-sm",
                    warn && "border-warning/50",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <Truck className="w-4 h-4 text-accent" />
                    <span className="font-bold">{r.veiculo_nome}</span>
                    <span className="text-xs text-muted-foreground ml-auto">{r.regiao_predominante}</span>
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
                    <div className="rounded bg-muted/50 py-2">
                      <div className="text-muted-foreground">Paradas</div>
                      <div className="font-bold">{r.qtd_paradas}</div>
                    </div>
                    <div className="rounded bg-muted/50 py-2">
                      <div className="text-muted-foreground">Peso</div>
                      <div className="font-bold">{pesoPct}%</div>
                    </div>
                    <div className="rounded bg-muted/50 py-2">
                      <div className="text-muted-foreground">Retorno</div>
                      <div className="font-bold">{r.retorno_previsto || "—"}</div>
                    </div>
                  </div>
                  <VehicleMetricsCompact rota={r} jornadaMax={jornadaMax} />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {!roteirizacao && !loading && (
        <div className="text-sm text-muted-foreground">
          Roteirização ainda não executada. Confirme a validação e acesse{" "}
          <a href="/roteirizar" className="text-accent underline">
            Montagem de Cargas
          </a>
          .
        </div>
      )}
    </div>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Truck;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="bg-card rounded-xl border border-border p-5 shadow-sm">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
        <Icon className="w-4 h-4" /> {label}
      </div>
      <div className="mt-2 text-3xl font-bold">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{hint}</div>
    </div>
  );
}
