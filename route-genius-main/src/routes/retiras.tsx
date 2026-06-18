import { createFileRoute } from "@tanstack/react-router";
import { Building2, Loader2, PackageCheck } from "lucide-react";
import { useMemo } from "react";

import {
  getStoredSessionId,
  useLogisticaSession,
} from "@/hooks/useLogisticaSession";

export const Route = createFileRoute("/retiras")({
  head: () => ({ meta: [{ title: "Retiras (FOB)" }] }),
  component: RetirasPage,
});

function RetirasPage() {
  const sessionId = getStoredSessionId();
  const { consolidadosQuery } = useLogisticaSession(sessionId);

  const retiras = useMemo(() => {
    if (!consolidadosQuery.data) return [];
    return consolidadosQuery.data.consolidados.filter(
      (c) => c.status === "RETIRA FOB" || c.tipo_frete === "RETIRA_FOB",
    );
  }, [consolidadosQuery.data]);

  const totalPeso = retiras.reduce((s, r) => s + r.peso_kg, 0);
  const totalValor = retiras.reduce((s, r) => s + r.valor_tt, 0);

  if (!sessionId) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Nenhuma sessão ativa. Execute o upload primeiro.
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Retiras (FOB)</h1>
        <p className="text-sm text-muted-foreground">
          Pedidos fora da frota própria — dados reais da ingestão
        </p>
      </div>

      {consolidadosQuery.isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Carregando…
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2 text-xs uppercase text-muted-foreground">
            <PackageCheck className="w-4 h-4" /> Total Retiras
          </div>
          <div className="mt-2 text-3xl font-bold">{retiras.length}</div>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="text-xs uppercase text-muted-foreground">Peso Total</div>
          <div className="mt-2 text-3xl font-bold">{totalPeso.toLocaleString("pt-BR")} kg</div>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="text-xs uppercase text-muted-foreground">Valor TT</div>
          <div className="mt-2 text-3xl font-bold">
            R$ {totalValor.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
          </div>
        </div>
      </div>

      {retiras.length === 0 && !consolidadosQuery.isLoading ? (
        <div className="rounded-xl border border-border bg-muted/30 p-6 text-sm text-muted-foreground">
          Nenhum pedido RETIRA FOB identificado nesta sessão.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {retiras.map((r) => (
            <div key={r.numero_pedido} className="rounded-xl border border-border bg-card p-5 shadow-sm">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
                  <Building2 className="w-5 h-5 text-accent" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold truncate">{r.cliente}</div>
                  <div className="text-xs text-muted-foreground font-mono">{r.numero_pedido}</div>
                  <div className="mt-2 text-sm">
                    {r.bairro_destino || r.bairro} · {r.cidade_destino || r.cidade}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-3 text-xs">
                    <span className="font-mono">{r.peso_kg.toLocaleString("pt-BR")} kg</span>
                    <span>R$ {r.valor_tt.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}</span>
                    <span className="px-2 py-0.5 rounded bg-muted">{r.representante}</span>
                  </div>
                  {r.motivo_bloqueio && (
                    <div className="mt-2 text-xs text-muted-foreground">{r.motivo_bloqueio}</div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
