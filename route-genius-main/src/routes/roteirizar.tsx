import { createFileRoute } from "@tanstack/react-router";
import { Download, Info, LayoutGrid, Loader2, Map, RotateCcw, Zap } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import { RouteKanbanBoard } from "@/components/logistica/RouteKanbanBoard";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  getStoredSessionId,
  useLogisticaSession,
} from "@/hooks/useLogisticaSession";
import { exportarRomaneio, exportarRomaneioCaminhao } from "@/lib/api-client";
import type { OperacaoDivisao } from "@/lib/logistica-types";

// Leaflet acessa `window` ao ser importado: o mapa só pode carregar no navegador.
const MapaRoteirizacao = lazy(() =>
  import("@/components/logistica/MapaRoteirizacao").then((m) => ({ default: m.MapaRoteirizacao })),
);
import type { PedidoConsolidado } from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/roteirizar")({
  head: () => ({ meta: [{ title: "Pronto para Roteirizar" }] }),
  component: RoteirizarPage,
});

function RoteirizarPage() {
  const sessionId = getStoredSessionId();
  const { consolidadosQuery, roteirizacaoQuery, roteirizarMutation, recomecarMutation, fecharMutation, equipeMutation, moverMutation, anteciparMutation, segundaViagemMutation, dividirMutation } =
    useLogisticaSession(sessionId);
  const [lastWarning, setLastWarning] = useState("");
  const [confirmarRecomeco, setConfirmarRecomeco] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportingCaminhaoId, setExportingCaminhaoId] = useState<string | null>(null);
  const [habilitandoSegundaViagemId, setHabilitandoSegundaViagemId] = useState<string | null>(null);
  const [visualizacao, setVisualizacao] = useState<"kanban" | "mapa">("kanban");

  const consolidadosByPedido = useMemo(() => {
    const map: Record<string, PedidoConsolidado> = {};
    consolidadosQuery.data?.consolidados.forEach((c) => {
      if (!map[c.numero_pedido]) map[c.numero_pedido] = c;
      if (c.numero_pedido_norm && !map[c.numero_pedido_norm]) map[c.numero_pedido_norm] = c;
      if (c.id_item) map[c.id_item] = c;
    });
    return map;
  }, [consolidadosQuery.data]);

  useEffect(() => {
    if (!sessionId || roteirizacaoQuery.data || roteirizacaoQuery.isFetching || roteirizarMutation.isPending) return;
    // Quadro ainda não montado (null) ou erro: monta pela primeira vez.
    if (roteirizacaoQuery.data === null || roteirizacaoQuery.isError) {
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
    recomecarMutation.isPending ||
    moverMutation.isPending ||
    anteciparMutation.isPending ||
    segundaViagemMutation.isPending;

  const data = roteirizacaoQuery.data ?? roteirizarMutation.data;
  const mensagemQuadro = roteirizarMutation.data?.mensagem || recomecarMutation.data?.mensagem || "";

  const handleEquipe = async (veiculoId: string, equipe: { motorista: string; ajudante: string; placa: string }) => {
    if (!sessionId) return;
    await equipeMutation.mutateAsync({ sid: sessionId, veiculoId, equipe });
  };

  const handleFecharVeiculo = async (veiculoId: string, fechado: boolean) => {
    if (!sessionId) return;
    const r = await fecharMutation.mutateAsync({ sid: sessionId, veiculoId, fechado });
    setLastWarning(r.warning ?? "");
  };

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

  const handleExportRomaneioCaminhao = async (caminhaoId: string) => {
    if (!sessionId) return;
    setExportingCaminhaoId(caminhaoId);
    try {
      await exportarRomaneioCaminhao(sessionId, caminhaoId);
    } finally {
      setExportingCaminhaoId(null);
    }
  };

  const handleHabilitarSegundaViagem = async (veiculoId: string) => {
    if (!sessionId) return;
    setHabilitandoSegundaViagemId(veiculoId);
    try {
      await segundaViagemMutation.mutateAsync({ sid: sessionId, veiculoId });
    } finally {
      setHabilitandoSegundaViagemId(null);
    }
  };

  const handleDivisao = async (operacao: OperacaoDivisao) => {
    if (!sessionId) return;
    const resp = await dividirMutation.mutateAsync({ sid: sessionId, operacao });
    setLastWarning(resp.warning ?? "");
  };

  const handleAntecipar = async (payload: {
    numero_pedido: string;
    motivo_adiantamento: string;
    representante_autorizou: string;
  }) => {
    await anteciparMutation.mutateAsync({ sid: sessionId, body: payload });
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
            title="Distribui só o que está sem lugar (fila, linhas novas, pendências resolvidas). Não desfaz nada do que você montou e não mexe em caminhões fechados."
            className={cn(
              "inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-semibold",
              loading ? "bg-muted text-muted-foreground" : "bg-accent text-accent-foreground",
            )}
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            Sugerir alocação
          </button>
          <button
            disabled={loading || !data}
            onClick={() => setConfirmarRecomeco(true)}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-md text-sm border border-destructive/40 text-destructive hover:bg-destructive/10 disabled:opacity-50"
          >
            <RotateCcw className="w-4 h-4" /> Recomeçar do zero
          </button>
        </div>
      </div>

      {mensagemQuadro && (
        <div className="rounded-lg border border-accent/30 bg-accent/5 px-4 py-2 text-sm">{mensagemQuadro}</div>
      )}

      <Dialog open={confirmarRecomeco} onOpenChange={setConfirmarRecomeco}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Recomeçar o quadro do zero?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Tudo o que foi montado à mão (cargas arrastadas, divisões, ajustes, caminhões fechados) será
            perdido e o sistema monta um quadro novo. Para só encaixar o que está na fila, use{" "}
            <b>Sugerir alocação</b>.
          </p>
          <DialogFooter>
            <button type="button" className="px-4 py-2 text-sm rounded-md border" onClick={() => setConfirmarRecomeco(false)}>
              Cancelar
            </button>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md bg-destructive text-destructive-foreground"
              onClick={async () => {
                setConfirmarRecomeco(false);
                await recomecarMutation.mutateAsync(sessionId);
              }}
            >
              Recomeçar do zero
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {loading && !data && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Carregando roteirização…
        </div>
      )}

      {data && (
        <Tabs
          value={visualizacao}
          onValueChange={(v) => setVisualizacao(v as "kanban" | "mapa")}
          className="w-full"
        >
          <TabsList>
            <TabsTrigger value="kanban" className="gap-1.5">
              <LayoutGrid className="w-4 h-4" />
              Visualização Kanban
            </TabsTrigger>
            <TabsTrigger value="mapa" className="gap-1.5">
              <Map className="w-4 h-4" />
              Visualização Mapa
            </TabsTrigger>
          </TabsList>

          <TabsContent value="kanban" className="mt-4">
            <RouteKanbanBoard
              data={data}
              loading={moverMutation.isPending || anteciparMutation.isPending || dividirMutation.isPending}
              onMove={handleMove}
              onDivisao={handleDivisao}
              onFecharVeiculo={handleFecharVeiculo}
              onEquipe={handleEquipe}
              onAntecipar={handleAntecipar}
              onExportRomaneio={handleExportRomaneioCaminhao}
              exportingCaminhaoId={exportingCaminhaoId}
              onHabilitarSegundaViagem={handleHabilitarSegundaViagem}
              habilitandoSegundaViagemId={habilitandoSegundaViagemId}
              warning={lastWarning}
              consolidadosByPedido={consolidadosByPedido}
            />
          </TabsContent>

          <TabsContent value="mapa" className="mt-4">
            {typeof window !== "undefined" && (
              <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Carregando mapa…</div>}>
                <MapaRoteirizacao data={data} consolidadosByPedido={consolidadosByPedido} />
              </Suspense>
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
