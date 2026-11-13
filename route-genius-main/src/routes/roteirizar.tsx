import { Link, createFileRoute } from "@tanstack/react-router";
import {
  Check,
  Columns2,
  Download,
  Info,
  LayoutGrid,
  Loader2,
  Map,
  MoreHorizontal,
  RotateCcw,
  Route as IconeRota,
  Search,
  Undo2,
  X,
  Zap,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import { RouteKanbanBoard } from "@/components/logistica/RouteKanbanBoard";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getStoredSessionId, useLogisticaSession } from "@/hooks/useLogisticaSession";
import {
  desfazerQuadro,
  exportarRomaneio,
  exportarRomaneioCaminhao,
  moverLote,
  otimizarSequencia,
} from "@/lib/api-client";
import type { MoverLoteRequest, OperacaoDivisao, Roteirizacao } from "@/lib/logistica-types";
import { casaBusca, checklist, idDaCarga } from "@/lib/montagem";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

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
  const {
    consolidadosQuery,
    roteirizacaoQuery,
    roteirizarMutation,
    recomecarMutation,
    fecharMutation,
    naoSaiuMutation,
    equipeMutation,
    moverMutation,
    anteciparMutation,
    segundaViagemMutation,
    dividirMutation,
  } = useLogisticaSession(sessionId);
  const queryClient = useQueryClient();
  const [lastWarning, setLastWarning] = useState("");
  const [confirmarRecomeco, setConfirmarRecomeco] = useState(false);
  const [otimizando, setOtimizando] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportingCaminhaoId, setExportingCaminhaoId] = useState<string | null>(null);
  const [habilitandoSegundaViagemId, setHabilitandoSegundaViagemId] = useState<string | null>(null);
  const [visualizacao, setVisualizacaoEstado] = useState<Visualizacao>(() => {
    try {
      const v = localStorage.getItem("montagem_visualizacao");
      return v === "lado" || v === "mapa" ? v : "kanban";
    } catch {
      return "kanban";
    }
  });
  const setVisualizacao = (v: Visualizacao) => {
    setVisualizacaoEstado(v);
    try {
      localStorage.setItem("montagem_visualizacao", v);
    } catch {
      /* navegador sem armazenamento */
    }
  };
  const [busca, setBusca] = useState("");
  const [mensagemFechada, setMensagemFechada] = useState("");
  const [desfazendo, setDesfazendo] = useState(false);
  const [confirmarExportar, setConfirmarExportar] = useState<string[] | null>(null);

  const consolidadosByPedido = useMemo(() => {
    const map: Record<string, PedidoConsolidado> = {};
    consolidadosQuery.data?.consolidados.forEach((c) => {
      if (!map[c.numero_pedido]) map[c.numero_pedido] = c;
      if (c.numero_pedido_norm && !map[c.numero_pedido_norm]) map[c.numero_pedido_norm] = c;
      if (c.id_item) map[c.id_item] = c;
    });
    return map;
  }, [consolidadosQuery.data]);

  const conferido = !!consolidadosQuery.data?.validated;

  useEffect(() => {
    if (
      !sessionId ||
      !conferido ||
      roteirizacaoQuery.data ||
      roteirizacaoQuery.isFetching ||
      roteirizarMutation.isPending
    )
      return;
    // Só monta o quadro depois que o operador conferiu a lista (Pendências → Confirmar).
    if (roteirizacaoQuery.data === null || roteirizacaoQuery.isError) {
      roteirizarMutation.mutate(sessionId);
    }
  }, [
    sessionId,
    conferido,
    roteirizacaoQuery.data,
    roteirizacaoQuery.isError,
    roteirizacaoQuery.isFetching,
    roteirizarMutation,
  ]);

  if (!sessionId) {
    return (
      <div className="p-6">
        <div className="rounded-xl border border-warning/40 bg-warning/10 p-6 text-sm">
          Nenhuma sessão ativa. Complete upload e validação primeiro.
        </div>
      </div>
    );
  }

  if (consolidadosQuery.data && !conferido) {
    return (
      <div className="p-6">
        <div className="rounded-xl border border-warning/40 bg-warning/10 p-6 text-sm space-y-2">
          <div className="font-semibold">A lista ainda não foi conferida.</div>
          <div>
            Nada vai para os caminhões sem a sua aprovação. Confira a lista e clique em{" "}
            <b>Confirmar leitura e montar cargas</b>.
          </div>
          <Link to="/pendencias" className="inline-block font-semibold text-accent underline">
            Ir para a conferência
          </Link>
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
  const mensagemQuadro =
    roteirizarMutation.data?.mensagem || recomecarMutation.data?.mensagem || "";

  const handleEquipe = async (
    veiculoId: string,
    equipe: { motorista: string; ajudante: string; placa: string },
  ) => {
    if (!sessionId) return;
    await equipeMutation.mutateAsync({ sid: sessionId, veiculoId, equipe });
  };

  const handleOtimizar = async () => {
    if (!sessionId) return;
    setOtimizando(true);
    try {
      const r = await otimizarSequencia(sessionId);
      queryClient.setQueryData(["roteirizacao", sessionId], r.roteirizacao);
      setLastWarning(r.warning ?? "");
    } catch (e) {
      setLastWarning(e instanceof Error ? e.message : "Não foi possível otimizar.");
    } finally {
      setOtimizando(false);
    }
  };

  const handleNaoSaiu = async (veiculoId: string, naoSaiu: boolean) => {
    if (!sessionId) return;
    const r = await naoSaiuMutation.mutateAsync({ sid: sessionId, veiculoId, naoSaiu });
    setLastWarning(r.warning ?? "");
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
    liberar_representante?: boolean;
    autorizado_por?: string;
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

  const aplicar = (r: { warning?: string; roteirizacao: Roteirizacao }) => {
    queryClient.setQueryData(["roteirizacao", sessionId], r.roteirizacao);
    setLastWarning(r.warning ?? "");
  };

  const handleMoverLote = async (payload: MoverLoteRequest) => {
    if (!sessionId) return;
    aplicar(await moverLote(sessionId, payload));
  };

  const handleDesfazer = async () => {
    if (!sessionId || desfazendo || !data?.desfazer_disponivel) return;
    setDesfazendo(true);
    try {
      aplicar(await desfazerQuadro(sessionId));
    } catch (e) {
      setLastWarning(e instanceof Error ? e.message : "Não foi possível desfazer.");
    } finally {
      setDesfazendo(false);
    }
  };

  const handleOtimizarVeiculo = async (veiculoId: string) => {
    if (!sessionId) return;
    try {
      aplicar(await otimizarSequencia(sessionId, veiculoId));
    } catch (e) {
      setLastWarning(e instanceof Error ? e.message : "Não foi possível otimizar.");
    }
  };

  // ---------------------------------------------------------------- etapas
  const jornadaMax = data?.jornada_maxima_minutos || 600;
  const comCarga = (data?.rotas ?? []).filter(
    (r) =>
      (data?.itens_por_veiculo[r.veiculo_id]?.length ?? 0) > 0 &&
      !(data?.veiculos_nao_sairam ?? []).includes(r.veiculo_id),
  );
  const checks = comCarga.map((r) => ({
    rota: r,
    nome: data?.painel_veiculos?.[r.veiculo_id]?.nome ?? r.veiculo_nome,
    check: checklist(
      r,
      data?.painel_veiculos?.[r.veiculo_id],
      data?.equipe_por_veiculo?.[r.veiculo_id],
      data?.itens_por_veiculo[r.veiculo_id] ?? [],
      jornadaMax,
    ),
  }));
  const naFila = data?.backlog.length ?? 0;
  const comAviso = comCarga.filter(
    (r) =>
      data?.painel_veiculos?.[r.veiculo_id]?.sugestao_corredor ||
      r.peso_alocado_kg > r.capacidade_kg,
  ).length;
  const semOrdem = comCarga.filter(
    (r) => !data?.painel_veiculos?.[r.veiculo_id]?.ordem_otimizada,
  ).length;
  const semEquipe = comCarga.filter((r) => {
    const e = data?.equipe_por_veiculo?.[r.veiculo_id];
    return !e?.motorista?.trim() || !e?.placa?.trim();
  }).length;
  const prontos = checks.filter((c) => c.check.pronto).length;

  const exportar = () => {
    const faltando = checks
      .filter((c) => !c.check.pronto)
      .map(
        (c) =>
          `${c.nome}: ${c.check.itens
            .filter((i) => !i.ok)
            .map((i) => i.texto.toLowerCase())
            .join("; ")}`,
      );
    if (faltando.length) setConfirmarExportar(faltando);
    else void handleExportRomaneio();
  };

  // ---------------------------------------------------------------- busca
  const achados = (() => {
    if (!data || !busca.trim()) return [] as string[];
    const todas = [
      ...Object.values(data.itens_por_veiculo).flat(),
      ...Object.values(data.itens_retorno_por_veiculo ?? {}).flat(),
      ...data.backlog,
      ...(data.backlog_futuro ?? []),
      ...(data.backlog_local ?? []),
      ...(data.coletas ?? []),
    ];
    return todas.filter((l) => casaBusca(l, busca)).map(idDaCarga);
  })();
  const irParaAchado = () => {
    const el = achados.length
      ? document.querySelector(`[data-card-id="${CSS.escape(achados[0])}"]`)
      : null;
    el?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
  };

  const mensagem = lastWarning || (mensagemQuadro !== mensagemFechada ? mensagemQuadro : "");

  const quadro = data && (
    <RouteKanbanBoard
      data={data}
      loading={
        moverMutation.isPending ||
        anteciparMutation.isPending ||
        dividirMutation.isPending ||
        desfazendo
      }
      onMove={handleMove}
      onMoverLote={handleMoverLote}
      onDesfazer={() => void handleDesfazer()}
      onOtimizarVeiculo={handleOtimizarVeiculo}
      onVerMapa={() => setVisualizacao(visualizacao === "kanban" ? "lado" : visualizacao)}
      compacto={visualizacao === "lado"}
      busca={busca}
      onDivisao={handleDivisao}
      onFecharVeiculo={handleFecharVeiculo}
      onNaoSaiu={handleNaoSaiu}
      onEquipe={handleEquipe}
      onAntecipar={handleAntecipar}
      onExportRomaneio={handleExportRomaneioCaminhao}
      exportingCaminhaoId={exportingCaminhaoId}
      onHabilitarSegundaViagem={handleHabilitarSegundaViagem}
      habilitandoSegundaViagemId={habilitandoSegundaViagemId}
      consolidadosByPedido={consolidadosByPedido}
    />
  );
  const mapa = data && typeof window !== "undefined" && (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Carregando mapa…</div>}>
      <MapaRoteirizacao
        data={data}
        consolidadosByPedido={consolidadosByPedido}
        sessionId={sessionId ?? undefined}
        onAtualizar={() => void consolidadosQuery.refetch()}
        compacto={visualizacao === "lado"}
      />
    </Suspense>
  );

  return (
    <div className="p-4 lg:p-6 space-y-3">
      {/* ------------------------------------------------ título + ferramentas */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="text-2xl font-bold tracking-tight">Montagem de Cargas</h1>
          <p className="text-sm text-muted-foreground">
            {data
              ? `${comCarga.length} ${comCarga.length === 1 ? "caminhão" : "caminhões"} com carga · ${prontos} pronto${prontos === 1 ? "" : "s"} para sair`
              : "Arraste os pedidos para os caminhões."}
          </p>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") irParaAchado();
              if (e.key === "Escape") setBusca("");
            }}
            placeholder="Buscar cliente ou pedido"
            className="h-9 w-64 rounded-md border border-input bg-background pl-8 pr-16 text-sm"
          />
          {busca && (
            <span className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1 text-xs text-muted-foreground">
              {achados.length}
              <button type="button" onClick={() => setBusca("")} aria-label="Limpar busca">
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          )}
        </div>
        <button
          type="button"
          disabled={!data?.desfazer_disponivel || desfazendo}
          onClick={() => void handleDesfazer()}
          title="Desfazer a última mudança (Ctrl+Z)"
          className="inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-sm hover:bg-muted disabled:opacity-40"
        >
          {desfazendo ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Undo2 className="h-4 w-4" />
          )}
          Desfazer
        </button>
        <div className="inline-flex h-9 rounded-md border p-0.5 text-sm">
          {(
            [
              ["kanban", LayoutGrid, "Quadro"],
              ["lado", Columns2, "Quadro + mapa"],
              ["mapa", Map, "Mapa"],
            ] as const
          ).map(([v, Icone, rotulo]) => (
            <button
              key={v}
              type="button"
              onClick={() => setVisualizacao(v)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded px-2.5",
                visualizacao === v
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icone className="h-4 w-4" />
              <span className="hidden xl:inline">{rotulo}</span>
            </button>
          ))}
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border hover:bg-muted"
              aria-label="Mais"
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            <DropdownMenuLabel className="flex items-start gap-2 text-xs font-normal text-muted-foreground">
              <Info className="mt-0.5 h-4 w-4 shrink-0" />
              Ordem de carga (LIFO): a última entrega entra primeiro no caminhão. A 1ª parada fica
              na porta.
            </DropdownMenuLabel>
            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
              Atalhos: Ctrl+clique seleciona · 1, 2… manda a seleção para o caminhão · F manda para
              a fila · Esc limpa · Ctrl+Z desfaz
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive"
              disabled={loading || !data}
              onClick={() => setConfirmarRecomeco(true)}
            >
              <RotateCcw className="mr-2 h-4 w-4" /> Recomeçar do zero…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* ------------------------------------------------ etapas */}
      {data && (
        <ol className="grid grid-cols-2 gap-2 md:grid-cols-5">
          <Etapa
            n={1}
            titulo="Distribuir"
            feito={naFila === 0}
            detalhe={naFila === 0 ? "Fila vazia" : `${naFila} na fila`}
            acao={
              <button
                type="button"
                disabled={loading}
                onClick={() => roteirizarMutation.mutate(sessionId)}
                title="Encaixa só o que está sem lugar. Não desfaz o que você montou nem mexe em caminhão fechado."
                className="inline-flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-xs font-semibold text-accent-foreground disabled:opacity-50"
              >
                {roteirizarMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Zap className="h-3.5 w-3.5" />
                )}
                Sugerir
              </button>
            }
          />
          <Etapa
            n={2}
            titulo="Ajustar"
            feito={comAviso === 0}
            detalhe={comAviso === 0 ? "Sem avisos nos caminhões" : `${comAviso} com aviso`}
          />
          <Etapa
            n={3}
            titulo="Ordenar"
            feito={semOrdem === 0}
            detalhe={semOrdem === 0 ? "Ordem otimizada" : `${semOrdem} sem ordem otimizada`}
            acao={
              <button
                type="button"
                disabled={loading || otimizando}
                onClick={() => void handleOtimizar()}
                title="Melhor ordem de entrega de cada caminhão aberto (distância e horário de recebimento)."
                className="inline-flex items-center gap-1 rounded-md border border-accent/50 px-2 py-1 text-xs font-semibold text-accent hover:bg-accent/10 disabled:opacity-50"
              >
                {otimizando ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <IconeRota className="h-3.5 w-3.5" />
                )}
                Otimizar
              </button>
            }
          />
          <Etapa
            n={4}
            titulo="Equipe"
            feito={semEquipe === 0}
            detalhe={semEquipe === 0 ? "Motorista e placa ok" : `${semEquipe} sem motorista/placa`}
          />
          <Etapa
            n={5}
            titulo="Exportar"
            feito={comCarga.length > 0 && prontos === comCarga.length}
            detalhe={`${prontos} de ${comCarga.length} prontos`}
            acao={
              <button
                type="button"
                disabled={!data || exporting || loading}
                onClick={exportar}
                className="inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-xs font-semibold text-primary-foreground disabled:opacity-50"
              >
                {exporting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                Romaneios
              </button>
            }
          />
        </ol>
      )}

      {mensagem && (
        <div className="flex items-start gap-2 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-sm">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
          <span className="flex-1">{mensagem}</span>
          <button
            type="button"
            onClick={() => {
              setLastWarning("");
              setMensagemFechada(mensagemQuadro);
            }}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Fechar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <Dialog open={confirmarRecomeco} onOpenChange={setConfirmarRecomeco}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Recomeçar o quadro do zero?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            O sistema monta um quadro novo e o que foi feito à mão (cargas arrastadas, divisões,
            caminhões fechados) sai. Dá para voltar com <b>Desfazer</b>. Para só encaixar o que está
            na fila, use <b>Sugerir</b>.
          </p>
          <DialogFooter>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md border"
              onClick={() => setConfirmarRecomeco(false)}
            >
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

      <Dialog open={!!confirmarExportar} onOpenChange={(o) => !o && setConfirmarExportar(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Ainda falta coisa nos caminhões</DialogTitle>
          </DialogHeader>
          <ul className="space-y-1 text-sm">
            {(confirmarExportar ?? []).map((t) => (
              <li key={t} className="rounded-md bg-amber-500/10 px-2 py-1 text-amber-900">
                {t}
              </li>
            ))}
          </ul>
          <DialogFooter>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md border"
              onClick={() => setConfirmarExportar(null)}
            >
              Voltar e arrumar
            </button>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md bg-primary text-primary-foreground"
              onClick={() => {
                setConfirmarExportar(null);
                void handleExportRomaneio();
              }}
            >
              Exportar mesmo assim
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {loading && !data && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Carregando roteirização…
        </div>
      )}

      {data &&
        (visualizacao === "mapa" ? (
          mapa
        ) : visualizacao === "lado" ? (
          <div className="grid grid-cols-[minmax(0,1fr)_minmax(340px,30%)] items-start gap-4">
            <div className="min-w-0">{quadro}</div>
            <div className="sticky top-2">{mapa}</div>
          </div>
        ) : (
          quadro
        ))}
    </div>
  );
}

function Etapa({
  n,
  titulo,
  feito,
  detalhe,
  acao,
}: {
  n: number;
  titulo: string;
  feito: boolean;
  detalhe: string;
  acao?: React.ReactNode;
}) {
  return (
    <li
      className={cn(
        "flex items-center gap-2 rounded-lg border px-2.5 py-2",
        feito ? "border-emerald-500/30 bg-emerald-500/5" : "bg-card",
      )}
    >
      <span
        className={cn(
          "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold",
          feito ? "bg-emerald-600 text-white" : "bg-muted text-foreground",
        )}
      >
        {feito ? <Check className="h-3.5 w-3.5" /> : n}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold leading-tight">{titulo}</div>
        <div
          className={cn(
            "truncate text-[11px]",
            feito ? "text-emerald-700" : "text-muted-foreground",
          )}
          title={detalhe}
        >
          {detalhe}
        </div>
      </div>
      {acao}
    </li>
  );
}

type Visualizacao = "kanban" | "lado" | "mapa";
