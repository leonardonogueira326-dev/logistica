import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { Truck, Inbox, PackageSearch, Loader2, AlertTriangle, CalendarClock, Download, MapPin, Clock } from "lucide-react";
import { useMemo, useState } from "react";

import { PedidoAuditSheet } from "@/components/logistica/PedidoAuditSheet";
import { PedidoKanbanCard, getCardId, type CardPedido } from "@/components/logistica/PedidoKanbanCard";
import { VehicleMetrics } from "@/components/logistica/VehicleMetrics";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  COLUMN_BACKLOG,
  COLUMN_BACKLOG_FUTURO,
  COLUMN_BACKLOG_LOCAL,
  COLUMN_COLETAS,
  MOTIVOS_BACKLOG,
  TEO_ALERTA_MIN,
  idRetornoVeiculo,
  type Roteirizacao,
  type PedidoConsolidado,
} from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

type PendingMove = {
  numeroPedido: string;
  origem: string;
  destino: string;
  forcar?: boolean;
};

export function RouteKanbanBoard({
  data,
  loading,
  onMove,
  onAntecipar,
  onDividir,
  onExportRomaneio,
  onHabilitarSegundaViagem,
  exportingCaminhaoId,
  habilitandoSegundaViagemId,
  warning,
  consolidadosByPedido = {},
}: {
  data: Roteirizacao;
  loading: boolean;
  onMove: (payload: {
    numero_pedido: string;
    destino: string;
    motivo?: string;
    forcar?: boolean;
  }) => Promise<void>;
  onAntecipar?: (payload: {
    numero_pedido: string;
    motivo_adiantamento: string;
    representante_autorizou: string;
  }) => Promise<void>;
  onDividir?: (payload: { id_carga: string; peso_kg: number }) => Promise<void>;
  onExportRomaneio?: (caminhaoId: string) => Promise<void>;
  onHabilitarSegundaViagem?: (veiculoId: string) => Promise<void>;
  exportingCaminhaoId?: string | null;
  habilitandoSegundaViagemId?: string | null;
  warning?: string;
  consolidadosByPedido?: Record<string, PedidoConsolidado>;
}) {
  const [activeCard, setActiveCard] = useState<CardPedido | null>(null);
  const [backlogModal, setBacklogModal] = useState<PendingMove | null>(null);
  const [motivo, setMotivo] = useState<string>(MOTIVOS_BACKLOG[0]);
  const [forceModal, setForceModal] = useState<PendingMove | null>(null);
  const [forceMessage, setForceMessage] = useState("");
  const [auditPedidoId, setAuditPedidoId] = useState<string | null>(null);
  const [anteciparModal, setAnteciparModal] = useState<string | null>(null);
  const [motivoAdiantamento, setMotivoAdiantamento] = useState("");
  const [repAutorizou, setRepAutorizou] = useState("");
  const [antecipando, setAntecipando] = useState(false);
  const [dividirModal, setDividirModal] = useState<{ id: string; peso: number; titulo: string } | null>(null);
  const [pesoDividir, setPesoDividir] = useState("");
  const [erroDividir, setErroDividir] = useState("");
  const [dividindo, setDividindo] = useState(false);

  const abrirDividir = (pedido: CardPedido) => {
    const peso = Number(pedido.peso_kg ?? 0);
    const of = String((pedido as Record<string, string>).of_ano ?? "");
    setDividirModal({
      id: getCardId(pedido),
      peso,
      titulo: `${String(pedido.cliente ?? "")} — ${String(pedido.numero_pedido ?? "")}${of ? ` OF ${of}` : ""}`,
    });
    setPesoDividir(String(Math.round(peso / 2)));
    setErroDividir("");
  };

  const confirmarDivisao = async () => {
    if (!dividirModal || !onDividir) return;
    const valor = Number(pesoDividir);
    if (!(valor > 0) || valor >= dividirModal.peso) {
      setErroDividir(`Informe um peso entre 0 e ${dividirModal.peso.toLocaleString("pt-BR")} kg.`);
      return;
    }
    setDividindo(true);
    try {
      await onDividir({ id_carga: dividirModal.id, peso_kg: valor });
      setDividirModal(null);
    } catch (e) {
      setErroDividir(e instanceof Error ? e.message : "Não foi possível dividir.");
    } finally {
      setDividindo(false);
    }
  };

  const jornadaMax = data.jornada_maxima_minutos || 600;

  const columns = useMemo(() => {
    type ColVariant = "default" | "futuro" | "local" | "retorno";
    type ColDef = {
      id: string;
      label: string;
      rota: Roteirizacao["rotas"][0] | null;
      icon: typeof Truck;
      variant: ColVariant;
      isRetorno?: boolean;
      veiculoBaseId?: string;
    };

    const vehicleCols: ColDef[] = [];
    for (const r of data.rotas) {
      vehicleCols.push({
        id: r.veiculo_id,
        label: r.veiculo_nome,
        rota: r,
        icon: Truck,
        variant: "default",
      });
      if (data.viagens_retorno_habilitadas?.includes(r.veiculo_id)) {
        vehicleCols.push({
          id: idRetornoVeiculo(r.veiculo_id),
          label: `${r.veiculo_nome} - Retorno`,
          rota: r,
          icon: Truck,
          variant: "retorno",
          isRetorno: true,
          veiculoBaseId: r.veiculo_id,
        });
      }
    }

    return [
      ...vehicleCols,
      {
        id: COLUMN_BACKLOG_FUTURO,
        label: "Backlog Futuro",
        rota: null,
        icon: CalendarClock,
        variant: "futuro" as const,
      },
      {
        id: COLUMN_BACKLOG_LOCAL,
        label: "Fila de Entregas Locais",
        rota: null,
        icon: MapPin,
        variant: "local" as const,
      },
      { id: COLUMN_BACKLOG, label: "Fila de Espera", rota: null, icon: Inbox, variant: "default" as const },
      { id: COLUMN_COLETAS, label: "Coletas", rota: null, icon: PackageSearch, variant: "default" as const },
    ];
  }, [data.rotas, data.viagens_retorno_habilitadas]);

  const destinos = columns.map((c) => ({ id: c.id, label: c.label }));

  const itemsByColumn = useMemo(() => {
    const map: Record<string, CardPedido[]> = {};
    for (const col of columns) map[col.id] = [];

    for (const r of data.rotas) {
      map[r.veiculo_id] = [...(data.itens_por_veiculo[r.veiculo_id] ?? [])];
      if (data.viagens_retorno_habilitadas?.includes(r.veiculo_id)) {
        map[idRetornoVeiculo(r.veiculo_id)] = [
          ...(data.itens_retorno_por_veiculo?.[r.veiculo_id] ?? []),
        ];
      }
    }
    map[COLUMN_BACKLOG_FUTURO] = [...(data.backlog_futuro ?? [])];
    map[COLUMN_BACKLOG_LOCAL] = [...(data.backlog_local ?? [])];
    map[COLUMN_BACKLOG] = [...data.backlog];
    map[COLUMN_COLETAS] = [...(data.coletas ?? [])];
    return map;
  }, [columns, data]);

  const auditPedido = useMemo((): PedidoConsolidado | null => {
    if (!auditPedidoId) return null;
    if (consolidadosByPedido[auditPedidoId]) {
      return consolidadosByPedido[auditPedidoId];
    }
    for (const items of Object.values(itemsByColumn)) {
      const card = items.find((p) => getCardId(p) === auditPedidoId);
      if (card) {
        return {
          numero_pedido: String(card.numero_pedido ?? ""),
          numero_pedido_norm: String(card.numero_pedido ?? ""),
          id_item: String((card as Record<string, string>).id_item ?? getCardId(card)),
          of_ano: String((card as Record<string, string>).of_ano ?? ""),
          cliente: String(card.cliente ?? ""),
          cliente_codigo: String(card.cliente_codigo ?? ""),
          peso_kg: Number(card.peso_kg ?? 0),
          valor_tt: 0,
          cidade: String(card.cidade_destino ?? ""),
          estado: "",
          bairro: String(card.bairro_destino ?? ""),
          cidade_destino: String(card.cidade_destino ?? ""),
          estado_destino: "",
          bairro_destino: String(card.bairro_destino ?? ""),
          cep: String(card.cep_destino ?? ""),
          cep_destino: String(card.cep_destino ?? ""),
          representante: String(card.representante ?? ""),
          rota_logistica: String(card.rota_logistica ?? ""),
          enriquecido_mestre: String(card.enriquecido_mestre ?? "NAO"),
          status: "LIBERADO",
          motivo_bloqueio: String((card as Record<string, string>).motivo ?? ""),
          tipo_frete: "",
          is_spyder: String(card.is_spyder ?? "NAO"),
          is_dimensao_longa: String(card.is_dimensao_longa ?? "NAO"),
          exige_syder: "NAO",
          motivo_alocacao: "",
          fontes: "",
          auditoria: "",
          observacao_comercial: "",
          data_producao: String((card as Record<string, string>).data_producao ?? ""),
          revisao_obrigatoria: "NAO",
          motivo_quarentena: "",
          palavra_chave_quarentena: "",
          flag_revisao_llm: "NAO",
          sugestao_llm_status: "",
          status_ia: "NAO_APLICAVEL",
          tipo_frete_regex: "",
        } as PedidoConsolidado;
      }
    }
    return null;
  }, [auditPedidoId, consolidadosByPedido, itemsByColumn]);

  const executeMove = async (move: PendingMove & { motivo?: string }) => {
    try {
      await onMove({
        numero_pedido: move.numeroPedido,
        destino: move.destino,
        motivo: move.motivo,
        forcar: move.forcar,
      });
      setBacklogModal(null);
      setForceModal(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro ao mover";
      if (!move.forcar && move.destino !== COLUMN_BACKLOG) {
        setForceMessage(msg);
        setForceModal({ ...move, forcar: true });
      } else {
        throw err;
      }
    }
  };

  const requestMove = (numeroPedido: string, origem: string, destino: string) => {
    if (origem === destino) return;
    if (destino === COLUMN_BACKLOG) {
      setMotivo(MOTIVOS_BACKLOG[0]);
      setBacklogModal({ numeroPedido, origem, destino });
      return;
    }
    void executeMove({ numeroPedido, origem, destino });
  };

  const confirmarAntecipacao = async () => {
    if (!anteciparModal || !onAntecipar || !motivoAdiantamento.trim()) return;
    setAntecipando(true);
    try {
      await onAntecipar({
        numero_pedido: anteciparModal,
        motivo_adiantamento: motivoAdiantamento.trim(),
        representante_autorizou: repAutorizou.trim(),
      });
      setAnteciparModal(null);
      setMotivoAdiantamento("");
      setRepAutorizou("");
    } finally {
      setAntecipando(false);
    }
  };

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  const handleDragStart = (event: DragStartEvent) => {
    const payload = event.active.data.current as { pedido: CardPedido } | undefined;
    setActiveCard(payload?.pedido ?? null);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveCard(null);
    const { active, over } = event;
    if (!over) return;

    const activeData = active.data.current as { pedido: CardPedido; columnId: string } | undefined;
    if (!activeData) return;

    const numeroPedido = getCardId(activeData.pedido);
    const origem = activeData.columnId;

    let destino = String(over.id);
    if (destino.includes("::")) {
      destino = destino.split("::")[0];
    }

    requestMove(numeroPedido, origem, destino);
  };

  return (
    <>
      {warning && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {warning}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-4">
          <Loader2 className="w-4 h-4 animate-spin" /> Atualizando roteirização…
        </div>
      )}

      <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <TooltipProvider delayDuration={200}>
        <div className="flex gap-4 overflow-x-auto pb-4 min-h-[480px]">
          {columns.map((col) => (
            <KanbanColumn
              key={col.id}
              id={col.id}
              title={col.label}
              icon={col.icon}
              rota={col.rota}
              jornadaMax={jornadaMax}
              items={itemsByColumn[col.id] ?? []}
              destinos={destinos}
              variant={col.variant}
              onMoveTo={(destino, pedido) =>
                requestMove(getCardId(pedido), col.id, destino)
              }
              onOpenAudit={setAuditPedidoId}
              onAntecipar={col.variant === "futuro" ? setAnteciparModal : undefined}
              onDividir={onDividir ? abrirDividir : undefined}
              onExportRomaneio={col.rota ? onExportRomaneio : undefined}
              exportingRomaneio={exportingCaminhaoId === col.id}
              onHabilitarSegundaViagem={
                col.rota && !col.isRetorno ? onHabilitarSegundaViagem : undefined
              }
              habilitandoSegundaViagem={habilitandoSegundaViagemId === col.id}
              viagensRetornoHabilitadas={data.viagens_retorno_habilitadas ?? []}
              metricasRetorno={data.metricas_retorno ?? {}}
              isRetorno={col.isRetorno}
              veiculoBaseId={col.veiculoBaseId}
            />
          ))}
        </div>
        </TooltipProvider>
        <DragOverlay>
          {activeCard ? (
            <div className="w-[280px] opacity-90">
              <PedidoKanbanCard
                pedido={activeCard}
                columnId=""
                destinos={[]}
                onMoveTo={() => {}}
                dragging
              />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

      <Dialog open={!!backlogModal} onOpenChange={(o) => !o && setBacklogModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Motivo do Backlog</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Pedido <strong>{backlogModal?.numeroPedido}</strong> será enviado para a fila de espera.
          </p>
          <Select value={motivo} onValueChange={setMotivo}>
            <SelectTrigger>
              <SelectValue placeholder="Selecione o motivo" />
            </SelectTrigger>
            <SelectContent>
              {MOTIVOS_BACKLOG.map((m) => (
                <SelectItem key={m} value={m}>
                  {m}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <DialogFooter>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md border"
              onClick={() => setBacklogModal(null)}
            >
              Cancelar
            </button>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md bg-accent text-accent-foreground"
              onClick={() =>
                backlogModal &&
                void executeMove({ ...backlogModal, motivo })
              }
            >
              Confirmar
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!dividirModal} onOpenChange={(o) => !o && setDividirModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Dividir carga</DialogTitle>
          </DialogHeader>
          {dividirModal && (
            <div className="space-y-3 text-sm">
              <p className="text-muted-foreground">{dividirModal.titulo}</p>
              <p>
                Peso desta carga: <b>{dividirModal.peso.toLocaleString("pt-BR")} kg</b>. A nova parte
                fica na mesma coluna — depois arraste para o outro caminhão.
              </p>
              <label className="block">
                <span className="text-xs text-muted-foreground">Peso da nova parte (kg)</span>
                <input
                  type="number"
                  min={1}
                  max={dividirModal.peso - 1}
                  autoFocus
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono"
                  value={pesoDividir}
                  onChange={(e) => {
                    setPesoDividir(e.target.value);
                    setErroDividir("");
                  }}
                  onKeyDown={(e) => e.key === "Enter" && void confirmarDivisao()}
                />
              </label>
              {Number(pesoDividir) > 0 && Number(pesoDividir) < dividirModal.peso && (
                <p className="text-xs text-muted-foreground">
                  Fica {(dividirModal.peso - Number(pesoDividir)).toLocaleString("pt-BR")} kg +{" "}
                  {Number(pesoDividir).toLocaleString("pt-BR")} kg
                </p>
              )}
              {erroDividir && <p className="text-xs text-destructive">{erroDividir}</p>}
            </div>
          )}
          <DialogFooter>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md border"
              onClick={() => setDividirModal(null)}
            >
              Cancelar
            </button>
            <button
              type="button"
              disabled={dividindo}
              className="px-4 py-2 text-sm rounded-md bg-accent text-accent-foreground disabled:opacity-50"
              onClick={() => void confirmarDivisao()}
            >
              {dividindo ? "Dividindo…" : "Dividir"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!forceModal} onOpenChange={(o) => !o && setForceModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Forçar movimentação?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{forceMessage}</p>
          <DialogFooter>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md border"
              onClick={() => setForceModal(null)}
            >
              Cancelar
            </button>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md bg-destructive text-destructive-foreground"
              onClick={() =>
                forceModal &&
                void executeMove({ ...forceModal, forcar: true })
              }
            >
              Forçar mesmo assim
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!anteciparModal} onOpenChange={(o) => !o && setAnteciparModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Antecipar Entrega</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Pedido <strong>{anteciparModal}</strong> entrará na fila de alocação de hoje.
          </p>
          <label className="block text-sm">
            <span className="text-xs font-medium text-muted-foreground">Motivo do adiantamento *</span>
            <textarea
              className="mt-1 w-full min-h-[72px] px-3 py-2 text-sm rounded-md border border-input bg-background"
              value={motivoAdiantamento}
              onChange={(e) => setMotivoAdiantamento(e.target.value)}
              placeholder="Ex.: cliente confirmou recebimento antecipado"
            />
          </label>
          <label className="block text-sm">
            <span className="text-xs font-medium text-muted-foreground">Representante que autorizou</span>
            <input
              className="mt-1 w-full px-3 py-2 text-sm rounded-md border border-input bg-background"
              value={repAutorizou}
              onChange={(e) => setRepAutorizou(e.target.value)}
              placeholder="Nome do representante"
            />
          </label>
          <DialogFooter>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md border"
              onClick={() => setAnteciparModal(null)}
            >
              Cancelar
            </button>
            <button
              type="button"
              disabled={!motivoAdiantamento.trim() || antecipando}
              className="px-4 py-2 text-sm rounded-md bg-primary text-primary-foreground disabled:opacity-50"
              onClick={() => void confirmarAntecipacao()}
            >
              {antecipando ? "Confirmando…" : "Confirmar antecipação"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <PedidoAuditSheet
        pedido={auditPedido}
        open={!!auditPedidoId}
        onOpenChange={(o) => !o && setAuditPedidoId(null)}
      />
    </>
  );
}

function KanbanColumn({
  id,
  title,
  icon: Icon,
  rota,
  jornadaMax,
  items,
  destinos,
  variant = "default",
  onMoveTo,
  onOpenAudit,
  onAntecipar,
  onDividir,
  onExportRomaneio,
  exportingRomaneio,
  onHabilitarSegundaViagem,
  habilitandoSegundaViagem,
  viagensRetornoHabilitadas,
  metricasRetorno,
  isRetorno,
  veiculoBaseId,
}: {
  id: string;
  title: string;
  icon: typeof Truck;
  rota: Roteirizacao["rotas"][0] | null;
  jornadaMax: number;
  items: CardPedido[];
  destinos: { id: string; label: string }[];
  variant?: "default" | "futuro" | "local" | "retorno";
  onMoveTo: (destino: string, pedido: CardPedido) => void;
  onOpenAudit: (numeroPedido: string) => void;
  onAntecipar?: (numeroPedido: string) => void;
  onDividir?: (pedido: CardPedido) => void;
  onExportRomaneio?: (caminhaoId: string) => Promise<void>;
  exportingRomaneio?: boolean;
  onHabilitarSegundaViagem?: (veiculoId: string) => Promise<void>;
  habilitandoSegundaViagem?: boolean;
  viagensRetornoHabilitadas?: string[];
  metricasRetorno?: Roteirizacao["metricas_retorno"];
  isRetorno?: boolean;
  veiculoBaseId?: string;
}) {
  const { setNodeRef, isOver } = useDroppable({ id, data: { columnId: id } });

  const teoMin = isRetorno && veiculoBaseId
    ? parseInt(metricasRetorno?.[veiculoBaseId]?.teo_minutos ?? "0", 10)
    : parseInt(rota?.teo_minutos ?? rota?.tempo_total_min ?? "0", 10);
  const teoLabel = isRetorno && veiculoBaseId
    ? metricasRetorno?.[veiculoBaseId]?.teo_hhmm ?? formatTeoMin(teoMin)
    : rota?.teo_hhmm || formatTeoMin(teoMin);

  const mostrarSegundaViagem =
    rota &&
    !isRetorno &&
    rota.segunda_viagem_elegivel &&
    !viagensRetornoHabilitadas?.includes(rota.veiculo_id) &&
    onHabilitarSegundaViagem;

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex w-[300px] shrink-0 flex-col rounded-xl border",
        variant === "futuro" && "border-muted-foreground/30 bg-muted/15",
        variant === "local" && "border-emerald-500/30 bg-emerald-500/5",
        variant === "retorno" && "border-success/40 bg-success/5",
        variant === "default" && rota?.alerta_elastico && "border-warning/50 bg-warning/5",
        variant === "default" && !rota?.alerta_elastico && "border-border bg-muted/20",
        isOver && "ring-2 ring-accent bg-accent/5",
      )}
    >
      <div className={cn(
        "px-3 py-3 border-b border-border rounded-t-xl",
        variant === "futuro" ? "bg-muted/50" : "bg-card",
        variant === "local" && "bg-emerald-500/10",
        variant === "retorno" && "bg-success/10",
      )}>
        <div className="flex items-center gap-2">
          <Icon className={cn(
            "w-4 h-4",
            variant === "futuro" && "text-muted-foreground",
            variant === "local" && "text-emerald-600",
            variant === "retorno" && "text-success",
            variant === "default" && "text-accent",
          )} />
          <div className="font-semibold text-sm truncate flex-1 min-w-0">{title}</div>
          {rota && (
            <TeoBadge teoMin={teoMin} teoLabel={teoLabel} />
          )}
          {rota && onExportRomaneio && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  disabled={exportingRomaneio}
                  onClick={() => void onExportRomaneio(id)}
                  className={cn(
                    "shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-md border border-border",
                    "bg-background text-muted-foreground hover:text-foreground hover:bg-muted/60",
                    "disabled:opacity-50 disabled:pointer-events-none",
                  )}
                  aria-label="Exportar Romaneio"
                >
                  {exportingRomaneio ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Download className="w-3.5 h-3.5" />
                  )}
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom">Exportar Romaneio</TooltipContent>
            </Tooltip>
          )}
          <span className="text-xs text-muted-foreground shrink-0">{items.length}</span>
        </div>
        {variant === "futuro" && (
          <div className="mt-1 text-[11px] text-muted-foreground">
            Pedidos com recebimento futuro — visíveis para decisão
          </div>
        )}
        {variant === "local" && (
          <div className="mt-1 text-[11px] text-muted-foreground">
            Americana, Santa Bárbara d&apos;Oeste e SBO — 2ª viagem local
          </div>
        )}
        {variant === "retorno" && (
          <div className="mt-1 text-[11px] text-muted-foreground">
            Romaneio independente · turno da tarde
          </div>
        )}
        {mostrarSegundaViagem && (
          <button
            type="button"
            disabled={habilitandoSegundaViagem}
            onClick={() => void onHabilitarSegundaViagem!(rota!.veiculo_id)}
            className={cn(
              "mt-2 w-full inline-flex items-center justify-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold",
              "bg-success/15 text-success border border-success/40 hover:bg-success/25",
              "disabled:opacity-50",
            )}
          >
            {habilitandoSegundaViagem ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              "+ Habilitar 2ª Viagem"
            )}
          </button>
        )}
        {rota && !isRetorno && (
          <>
            <div className="mt-1 text-[11px] text-muted-foreground">
              {rota.regiao_predominante} · retorno {rota.retorno_previsto}
            </div>
            <VehicleMetrics rota={rota} jornadaMax={jornadaMax} />
            {rota.alerta_elastico && rota.mensagem_alerta_elastico && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="mt-2 flex items-start gap-1.5 rounded-md border border-warning/50 bg-warning/15 px-2 py-1.5 text-[11px] text-warning-foreground">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-warning" />
                    <span className="leading-snug">{rota.mensagem_alerta_elastico}</span>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="max-w-[260px]">
                  {rota.mensagem_alerta_elastico}
                </TooltipContent>
              </Tooltip>
            )}
          </>
        )}
        {rota && isRetorno && veiculoBaseId && (
          <div className="mt-2 text-[10px] text-muted-foreground">
            Peso: {(metricasRetorno?.[veiculoBaseId]?.peso_alocado_kg ?? 0).toLocaleString("pt-BR")} kg
          </div>
        )}
      </div>
      <div className="flex-1 p-2 space-y-2 overflow-y-auto max-h-[560px]">
        {items.map((pedido) => (
          <PedidoKanbanCard
            key={`${id}::${getCardId(pedido)}`}
            pedido={pedido}
            columnId={id}
            destinos={destinos}
            variant={variant}
            onMoveTo={(dest) => onMoveTo(dest, pedido)}
            onOpenAudit={onOpenAudit}
            onAntecipar={onAntecipar}
            onDividir={onDividir ? () => onDividir(pedido) : undefined}
          />
        ))}
        {items.length === 0 && (
          <div className="text-xs text-center text-muted-foreground py-8 border border-dashed rounded-lg">
            Arraste pedidos aqui
          </div>
        )}
      </div>
    </div>
  );
}

function formatTeoMin(min: number) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}h${m.toString().padStart(2, "0")}`;
}

function TeoBadge({ teoMin, teoLabel }: { teoMin: number; teoLabel: string }) {
  const alerta = teoMin > TEO_ALERTA_MIN;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold font-mono",
        alerta
          ? "bg-destructive/15 text-destructive border border-destructive/40"
          : "bg-muted text-muted-foreground border border-border",
      )}
      title={alerta ? "TEO acima de 8h30 — alerta de jornada" : "Tempo Estimado de Operação"}
    >
      <Clock className="w-3 h-3" />
      {teoLabel}
    </span>
  );
}
