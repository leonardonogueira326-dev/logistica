import { createFileRoute } from "@tanstack/react-router";
import { Download, Info, Loader2, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { RouteKanbanBoard } from "@/components/logistica/RouteKanbanBoard";
import {
  getStoredSessionId,
  useLogisticaSession,
} from "@/hooks/useLogisticaSession";
import { exportarRomaneio } from "@/lib/api-client";
import type { PedidoConsolidado } from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/roteirizar")({
  head: () => ({ meta: [{ title: "Pronto para Roteirizar" }] }),
  component: RoteirizarPage,
});

function RoteirizarPage() {
  const sessionId = getStoredSessionId();
  const { consolidadosQuery, roteirizacaoQuery, roteirizarMutation, moverMutation } =
    useLogisticaSession(sessionId);
  const [lastWarning, setLastWarning] = useState("");
  const [exporting, setExporting] = useState(false);

  const consolidadosByPedido = useMemo(() => {
    const map: Record<string, PedidoConsolidado> = {};
    consolidadosQuery.data?.consolidados.forEach((c) => {
      map[c.numero_pedido] = c;
      if (c.numero_pedido_norm) map[c.numero_pedido_norm] = c;
    });
    return map;
  }, [consolidadosQuery.data]);

  useEffect(() => {
    if (!sessionId || roteirizacaoQuery.data || roteirizacaoQuery.isFetching) return;
    if (roteirizacaoQuery.isError) {
      roteirizarMutation.mutate(sessionId);
    }
  }, [sessionId, roteirizacaoQuery.data, roteirizacaoQuery.isError, roteirizacaoQuery.isFetching, roteirizarMutation]);

  if (!sessionId) {
    return (
      <div className="p-6">
        <div className="rounded-xl border border-warning/40 bg-warning/10 p-6 text-sm">
          Nenhuma sessão ativa. Complete upload e validação primeiro.
        </div>
      </div>
    );
  }

  const loading =
    roteirizacaoQuery.isLoading ||
    roteirizarMutation.isPending ||
    moverMutation.isPending;

  const data = roteirizacaoQuery.data ?? roteirizarMutation.data;

  const handleMove = async (payload: {
    numero_pedido: string;
    destino: string;
    motivo?: string;
    forcar?: boolean;
  }) => {
    const result = await moverMutation.mutateAsync({ sid: sessionId, body: payload });
    setLastWarning(result.warning ?? "");
  };

  const handleExportRomaneio = async () => {
    if (!sessionId) return;
    setExporting(true);
    try {
      await exportarRomaneio(sessionId);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Montagem de Cargas</h1>
          <p className="text-sm text-muted-foreground">
            Kanban interativo · arraste pedidos entre caminhões, backlog e coletas.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            disabled={!data || exporting || loading}
            onClick={handleExportRomaneio}
            className={cn(
              "inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-semibold shadow-sm",
              !data || exporting || loading
                ? "bg-muted text-muted-foreground cursor-not-allowed"
                : "bg-primary text-primary-foreground hover:opacity-90",
            )}
          >
            {exporting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            Exportar Romaneios
          </button>
          <div className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-md bg-accent/10 border border-accent/30 text-accent">
            <Info className="w-4 h-4" /> LIFO · maior seq. = carrega primeiro
          </div>
          <button
            disabled={loading}
            onClick={() => roteirizarMutation.mutate(sessionId)}
            className={cn(
              "inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-semibold",
              loading ? "bg-muted text-muted-foreground" : "bg-accent text-accent-foreground",
            )}
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            Recalcular automático
          </button>
        </div>
      </div>

      {loading && !data && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Carregando roteirização…
        </div>
      )}

      {data && (
        <RouteKanbanBoard
          data={data}
          loading={moverMutation.isPending}
          onMove={handleMove}
          warning={lastWarning}
          consolidadosByPedido={consolidadosByPedido}
        />
      )}
    </div>
  );
}
