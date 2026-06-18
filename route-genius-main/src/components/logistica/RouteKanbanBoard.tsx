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
import { Truck, Inbox, PackageSearch, Loader2, AlertTriangle } from "lucide-react";
import { useMemo, useState } from "react";

import { PedidoAuditSheet } from "@/components/logistica/PedidoAuditSheet";
import { PedidoKanbanCard, getCardId, type CardPedido } from "@/components/logistica/PedidoKanbanCard";
import { VehicleMetrics } from "@/components/logistica/VehicleMetrics";
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
  COLUMN_COLETAS,
  MOTIVOS_BACKLOG,
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
  warning?: string;
  consolidadosByPedido?: Record<string, PedidoConsolidado>;
}) {
  const [activeCard, setActiveCard] = useState<CardPedido | null>(null);
  const [backlogModal, setBacklogModal] = useState<PendingMove | null>(null);
  const [motivo, setMotivo] = useState<string>(MOTIVOS_BACKLOG[0]);
  const [forceModal, setForceModal] = useState<PendingMove | null>(null);
  const [forceMessage, setForceMessage] = useState("");
  const [auditPedidoId, setAuditPedidoId] = useState<string | null>(null);

  const auditPedido = useMemo((): PedidoConsolidado | null => {
    if (!auditPedidoId) return null;
    if (consolidadosByPedido[auditPedidoId]) {
      return consolidadosByPedido[auditPedidoId];
    }
    for (const items of Object.values(itemsByColumn)) {
      const card = items.find((p) => getCardId(p) === auditPedidoId);
      if (card) {
        return {
          numero_pedido: getCardId(card),
          numero_pedido_norm: getCardId(card),
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
        };
      }
    }
    return null;
  }, [auditPedidoId, consolidadosByPedido, itemsByColumn]);

  const jornadaMax = data.jornada_maxima_minutos || 600;

  const columns = useMemo(() => {
    const vehicleCols = data.rotas.map((r) => ({
      id: r.veiculo_id,
      label: r.veiculo_nome,
      rota: r,
      icon: Truck,
    }));
    return [
      ...vehicleCols,
      { id: COLUMN_BACKLOG, label: "Fila de Espera", rota: null, icon: Inbox },
      { id: COLUMN_COLETAS, label: "Coletas", rota: null, icon: PackageSearch },
    ];
  }, [data.rotas]);

  const destinos = columns.map((c) => ({ id: c.id, label: c.label }));

  const itemsByColumn = useMemo(() => {
    const map: Record<string, CardPedido[]> = {};
    for (const col of columns) map[col.id] = [];

    for (const r of data.rotas) {
      map[r.veiculo_id] = [...(data.itens_por_veiculo[r.veiculo_id] ?? [])];
    }
    map[COLUMN_BACKLOG] = [...data.backlog];
    map[COLUMN_COLETAS] = [...(data.coletas ?? [])];
    return map;
  }, [columns, data]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

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
              onMoveTo={(destino, pedido) =>
                requestMove(getCardId(pedido), col.id, destino)
              }
              onOpenAudit={setAuditPedidoId}
            />
          ))}
        </div>
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
  onMoveTo,
  onOpenAudit,
}: {
  id: string;
  title: string;
  icon: typeof Truck;
  rota: Roteirizacao["rotas"][0] | null;
  jornadaMax: number;
  items: CardPedido[];
  destinos: { id: string; label: string }[];
  onMoveTo: (destino: string, pedido: CardPedido) => void;
  onOpenAudit: (numeroPedido: string) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id, data: { columnId: id } });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex w-[300px] shrink-0 flex-col rounded-xl border border-border bg-muted/20",
        isOver && "ring-2 ring-accent bg-accent/5",
      )}
    >
      <div className="px-3 py-3 border-b border-border bg-card rounded-t-xl">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-accent" />
          <div className="font-semibold text-sm truncate">{title}</div>
          <span className="ml-auto text-xs text-muted-foreground">{items.length}</span>
        </div>
        {rota && (
          <>
            <div className="mt-1 text-[11px] text-muted-foreground">
              {rota.regiao_predominante} · retorno {rota.retorno_previsto}
            </div>
            <VehicleMetrics rota={rota} jornadaMax={jornadaMax} />
          </>
        )}
      </div>
      <div className="flex-1 p-2 space-y-2 overflow-y-auto max-h-[560px]">
        {items.map((pedido) => (
          <PedidoKanbanCard
            key={`${id}::${getCardId(pedido)}`}
            pedido={pedido}
            columnId={id}
            destinos={destinos}
            onMoveTo={(dest) => onMoveTo(dest, pedido)}
            onOpenAudit={onOpenAudit}
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
