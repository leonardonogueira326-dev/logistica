import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  rectIntersection,
  useDroppable,
  type CollisionDetection,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { Truck, Inbox, PackageSearch, Loader2, AlertTriangle, PhoneCall, Download, MapPin, Clock, Lock, LockOpen } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import { PedidoAuditSheet } from "@/components/logistica/PedidoAuditSheet";
import { PedidoKanbanCard, getCardId, type CardPedido } from "@/components/logistica/PedidoKanbanCard";
import { VehicleMetrics } from "@/components/logistica/VehicleMetrics";
import { BotaoCopiar } from "@/components/BotaoCopiar";
import { kg, mensagemRepresentante } from "@/lib/mensagens";
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
  SUFIXO_VIAGEM_RETORNO,
  idRetornoVeiculo,
  type EquipeVeiculo,
  type OperacaoDivisao,
  type Roteirizacao,
  type PedidoConsolidado,
} from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

type PendingMove = {
  numeroPedido: string;
  origem: string;
  destino: string;
  forcar?: boolean;
  liberarRepresentante?: boolean;
  autorizadoPor?: string;
};

const pendenciasDoCard = (p: CardPedido): string[] =>
  String((p as Record<string, string>).pendencias ?? "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

/** Comercial e peso zerado não sobem no caminhão: ficam na página Pendências. */
const cardTravado = (p: CardPedido) =>
  pendenciasDoCard(p).some((x) => x === "PAGAMENTO_ANTECIPADO" || x === "PESO_ZERADO");

const COLUNAS_NAO_VEICULO = new Set([COLUMN_BACKLOG, COLUMN_BACKLOG_FUTURO, COLUMN_BACKLOG_LOCAL, COLUMN_COLETAS]);

/** Motorista / ajudante / placa do caminhão no dia — salva quando o foco sai do grupo. */
function EquipeEditor({
  equipe,
  onSalvar,
}: {
  equipe?: EquipeVeiculo;
  onSalvar: (e: EquipeVeiculo) => Promise<void>;
}) {
  const vazio = { motorista: "", ajudante: "", placa: "" };
  const [valor, setValor] = useState<EquipeVeiculo>({ ...vazio, ...(equipe ?? {}) });
  const [editando, setEditando] = useState(false);
  // Atualiza com o servidor só quando ninguém está digitando (senão apagaria o que foi digitado)
  useEffect(() => {
    if (!editando) setValor({ ...vazio, ...(equipe ?? {}) });
  }, [equipe?.motorista, equipe?.ajudante, equipe?.placa, editando]); // eslint-disable-line react-hooks/exhaustive-deps
  const salvar = () => {
    setEditando(false);
    const atual = { ...vazio, ...(equipe ?? {}) };
    if (valor.motorista !== atual.motorista || valor.ajudante !== atual.ajudante || valor.placa !== atual.placa) {
      void onSalvar(valor);
    }
  };
  const campo = (k: keyof EquipeVeiculo, rotulo: string) => (
    <input
      className="w-full rounded border border-input bg-background px-1.5 py-0.5 text-[11px] uppercase"
      placeholder={rotulo}
      title={rotulo}
      value={valor[k]}
      onFocus={() => setEditando(true)}
      onChange={(e) => setValor((v) => ({ ...v, [k]: e.target.value }))}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
  return (
    <div
      className="mt-2 grid grid-cols-[1fr_1fr_72px] gap-1"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) salvar();
      }}
    >
      {campo("motorista", "Motorista")}
      {campo("ajudante", "Ajudante")}
      {campo("placa", "Placa")}
    </div>
  );
}

type AcoesDivisao = {
  dividir: (p: CardPedido) => void;
  ajustar: (p: CardPedido) => void;
  juntar: (p: CardPedido) => void;
  confirmar: (p: CardPedido) => void;
};

export function RouteKanbanBoard({
  data,
  loading,
  onMove,
  onAntecipar,
  onDivisao,
  onFecharVeiculo,
  onEquipe,
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
    liberar_representante?: boolean;
    autorizado_por?: string;
  }) => Promise<void>;
  onAntecipar?: (payload: {
    numero_pedido: string;
    motivo_adiantamento: string;
    representante_autorizou: string;
  }) => Promise<void>;
  onDivisao?: (operacao: OperacaoDivisao) => Promise<void>;
  onFecharVeiculo?: (veiculoId: string, fechado: boolean) => Promise<void>;
  onEquipe?: (veiculoId: string, equipe: EquipeVeiculo) => Promise<void>;
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
  const [dividirModal, setDividirModal] = useState<{
    modo: "dividir" | "ajustar";
    id: string;
    idItem: string;
    peso: number;
    titulo: string;
  } | null>(null);
  const [pesoDividir, setPesoDividir] = useState("");
  const [contrapartida, setContrapartida] = useState("");
  const [erroDividir, setErroDividir] = useState("");
  const [dividindo, setDividindo] = useState(false);
  const [repModal, setRepModal] = useState<(PendingMove & { titulo: string; representante: string; destinoLabel: string }) | null>(null);
  const [repQuem, setRepQuem] = useState("");
  const [repErro, setRepErro] = useState("");
  const [repSalvando, setRepSalvando] = useState(false);

  const tituloCard = (pedido: CardPedido) => {
    const of = String((pedido as Record<string, string>).of_ano ?? "");
    return `${String(pedido.cliente ?? "")} — ${String(pedido.numero_pedido ?? "")}${of ? ` OF ${of}` : ""}`;
  };

  const abrirDivisao = (pedido: CardPedido, modo: "dividir" | "ajustar") => {
    const peso = Number(pedido.peso_kg ?? 0);
    const raw = pedido as Record<string, string>;
    setDividirModal({
      modo,
      id: getCardId(pedido),
      idItem: String(raw.id_item || getCardId(pedido).split("@P")[0]),
      peso,
      titulo: tituloCard(pedido),
    });
    setPesoDividir(modo === "dividir" ? String(Math.round(peso / 2)) : String(peso));
    setContrapartida("");
    setErroDividir("");
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
    }

    return [
      {
        id: COLUMN_BACKLOG_FUTURO,
        label: "Consultar representante",
        rota: null,
        icon: PhoneCall,
        variant: "futuro" as const,
      },
      { id: COLUMN_BACKLOG, label: "Sobras / Fila de espera", rota: null, icon: Inbox, variant: "default" as const },
      ...vehicleCols,
      {
        id: COLUMN_BACKLOG_LOCAL,
        label: "Fila de Entregas Locais",
        rota: null,
        icon: MapPin,
        variant: "local" as const,
      },
      { id: COLUMN_COLETAS, label: "Coletas", rota: null, icon: PackageSearch, variant: "default" as const },
    ];
  }, [data.rotas, data.viagens_retorno_habilitadas]);

  // 2ª viagem fica dentro do card do caminhão, mas continua sendo um destino próprio.
  const destinos = columns.flatMap((c) => {
    const base = [{ id: c.id, label: c.label }];
    if (c.rota && data.viagens_retorno_habilitadas?.includes(c.id)) {
      base.push({ id: idRetornoVeiculo(c.id), label: `${c.label} · 2ª viagem` });
    }
    return base;
  });

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
    // Travados (comercial / peso zerado) ficam na página Pendências.
    map[COLUMN_BACKLOG_FUTURO] = (data.backlog_futuro ?? [])
      .filter((b) => !cardTravado(b))
      .sort((a, b) =>
        String(a.representante ?? "").localeCompare(String(b.representante ?? "")) ||
        String(a.cliente ?? "").localeCompare(String(b.cliente ?? "")),
      );
    map[COLUMN_BACKLOG_LOCAL] = [...(data.backlog_local ?? [])];
    map[COLUMN_BACKLOG] = [...data.backlog];
    map[COLUMN_COLETAS] = [...(data.coletas ?? [])];
    return map;
  }, [columns, data]);

  const travados = useMemo(() => (data.backlog_futuro ?? []).filter(cardTravado), [data.backlog_futuro]);

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
        liberar_representante: move.liberarRepresentante,
        autorizado_por: move.autorizadoPor,
      });
      setBacklogModal(null);
      setForceModal(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro ao mover";
      if (move.liberarRepresentante) throw err;
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
    if (!COLUNAS_NAO_VEICULO.has(destino)) {
      const card = (itemsByColumn[origem] ?? []).find((p) => getCardId(p) === numeroPedido);
      if (card && pendenciasDoCard(card).includes("CONSULTA_REPRESENTANTE")) {
        const rep = String(card.representante ?? "");
        setRepQuem(rep);
        setRepErro("");
        setRepModal({
          numeroPedido,
          origem,
          destino,
          titulo: tituloCard(card),
          representante: rep,
          destinoLabel: destinos.find((c) => c.id === destino)?.label ?? destino,
        });
        return;
      }
    }
    void executeMove({ numeroPedido, origem, destino });
  };


  const confirmarRepresentante = async () => {
    if (!repModal) return;
    setRepSalvando(true);
    setRepErro("");
    try {
      await executeMove({ ...repModal, liberarRepresentante: true, autorizadoPor: repQuem.trim() });
      setRepModal(null);
    } catch (e) {
      setRepErro(e instanceof Error ? e.message : "Não foi possível carregar.");
    } finally {
      setRepSalvando(false);
    }
  };

  const operar = async (operacao: OperacaoDivisao) => {
    if (!onDivisao) return;
    await onDivisao(operacao);
  };

  /** Todas as partes da mesma linha (pedido/item + OF), com a coluna onde estão. */
  const partesDaLinha = (idItem: string) => {
    const out: { id: string; peso: number; parte: string; coluna: string }[] = [];
    for (const col of destinos) {
      for (const p of itemsByColumn[col.id] ?? []) {
        const raw = p as Record<string, string>;
        const pid = String(raw.id_item || getCardId(p).split("@P")[0]);
        if (pid === idItem) {
          out.push({ id: getCardId(p), peso: Number(p.peso_kg ?? 0), parte: String(raw.parte ?? ""), coluna: col.label });
        }
      }
    }
    return out;
  };

  const confirmarDivisao = async () => {
    if (!dividirModal) return;
    const valor = Number(pesoDividir);
    const outras = partesDaLinha(dividirModal.idItem).filter((p) => p.id !== dividirModal.id);
    const contra = outras.find((p) => p.id === contrapartida) ?? [...outras].sort((a, b) => b.peso - a.peso)[0];
    const limite = dividirModal.modo === "dividir" ? dividirModal.peso : dividirModal.peso + (contra?.peso ?? 0);
    const invalido =
      dividirModal.modo === "dividir" ? !(valor > 0) || valor >= limite : !(valor > 0) || valor > limite;
    if (invalido) {
      setErroDividir(`Informe um peso entre 0 e ${limite.toLocaleString("pt-BR")} kg.`);
      return;
    }
    setDividindo(true);
    try {
      await operar(
        dividirModal.modo === "dividir"
          ? { op: "dividir", body: { id_carga: dividirModal.id, peso_kg: valor } }
          : {
              op: "ajustar",
              body: { id_carga: dividirModal.id, peso_kg: valor, id_carga_contrapartida: contra?.id ?? "" },
            },
      );
      setDividirModal(null);
    } catch (e) {
      setErroDividir(e instanceof Error ? e.message : "Não foi possível concluir.");
    } finally {
      setDividindo(false);
    }
  };

  const pendentesDivisao = useMemo(() => {
    const ids = new Set<string>();
    for (const items of Object.values(itemsByColumn)) {
      for (const p of items) {
        const raw = p as Record<string, string>;
        if (raw.divisao_automatica === "SIM") ids.add(String(raw.id_item || getCardId(p)));
      }
    }
    return ids.size;
  }, [itemsByColumn]);

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
    if (destino.includes("::") && !destino.endsWith(SUFIXO_VIAGEM_RETORNO)) {
      destino = destino.split("::")[0];
    }

    requestMove(numeroPedido, origem, destino);
  };

  return (
    <>
      {pendentesDivisao > 0 && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600" />
          <span>
            {pendentesDivisao === 1 ? "1 linha foi dividida" : `${pendentesDivisao} linhas foram divididas`}{" "}
            automaticamente por excesso de peso. Confira cada uma: no menu do card use{" "}
            <b>Ajustar divisão</b>, <b>Juntar partes</b> ou <b>Confirmar divisão</b>.
          </span>
        </div>
      )}

      {travados.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-2.5 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600" />
          <span>
            {travados.length === 1 ? "1 linha travada" : `${travados.length} linhas travadas`} (comercial ou peso
            zerado, {kg(travados.reduce((s, b) => s + Number(b.peso_kg ?? 0), 0))}) — não aparecem aqui até serem
            resolvidas.
          </span>
          <Link to="/pendencias" className="font-semibold text-accent underline">
            Abrir Pendências
          </Link>
        </div>
      )}

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

      <DndContext
        sensors={sensors}
        collisionDetection={colisao}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
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
              dataRef={Object.values(consolidadosByPedido)[0]?.data_referencia ?? ""}
              onMoveTo={(destino, pedido) =>
                requestMove(getCardId(pedido), col.id, destino)
              }
              onOpenAudit={setAuditPedidoId}
              onAntecipar={col.variant === "futuro" ? setAnteciparModal : undefined}
              onDivisao={
                onDivisao
                  ? {
                      dividir: (p: CardPedido) => abrirDivisao(p, "dividir"),
                      ajustar: (p: CardPedido) => abrirDivisao(p, "ajustar"),
                      juntar: (p: CardPedido) => void operar({ op: "juntar", body: { id_carga: getCardId(p) } }),
                      confirmar: (p: CardPedido) =>
                        void operar({ op: "confirmar", body: { id_carga: getCardId(p) } }),
                    }
                  : undefined
              }
              onExportRomaneio={col.rota ? onExportRomaneio : undefined}
              fechado={!!col.rota && (data.veiculos_fechados ?? []).includes(col.id)}
              equipe={col.rota && !col.isRetorno ? data.equipe_por_veiculo?.[col.id] : undefined}
              onSalvarEquipe={col.rota && !col.isRetorno && onEquipe ? (e: EquipeVeiculo) => onEquipe(col.id, e) : undefined}
              onToggleFechar={
                col.rota && !col.isRetorno && onFecharVeiculo
                  ? () => void onFecharVeiculo(col.id, !(data.veiculos_fechados ?? []).includes(col.id))
                  : undefined
              }
              exportingRomaneio={exportingCaminhaoId === col.id}
              onHabilitarSegundaViagem={
                col.rota && !col.isRetorno ? onHabilitarSegundaViagem : undefined
              }
              habilitandoSegundaViagem={habilitandoSegundaViagemId === col.id}
              viagensRetornoHabilitadas={data.viagens_retorno_habilitadas ?? []}
              metricasRetorno={data.metricas_retorno ?? {}}
              isRetorno={col.isRetorno}
              veiculoBaseId={col.veiculoBaseId}
              itensRetorno={
                col.rota && data.viagens_retorno_habilitadas?.includes(col.id)
                  ? itemsByColumn[idRetornoVeiculo(col.id)] ?? []
                  : undefined
              }
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
            <DialogTitle>{dividirModal?.modo === "ajustar" ? "Ajustar divisão" : "Dividir carga"}</DialogTitle>
          </DialogHeader>
          {dividirModal && (() => {
            const outras = partesDaLinha(dividirModal.idItem).filter((p) => p.id !== dividirModal.id);
            const contra =
              outras.find((p) => p.id === contrapartida) ?? [...outras].sort((a, b) => b.peso - a.peso)[0];
            const valor = Number(pesoDividir);
            const ajustar = dividirModal.modo === "ajustar";
            const limite = ajustar ? dividirModal.peso + (contra?.peso ?? 0) : dividirModal.peso;
            const restante = limite - valor;
            const fmt = (n: number) => n.toLocaleString("pt-BR");
            return (
              <div className="space-y-3 text-sm">
                <p className="text-muted-foreground">{dividirModal.titulo}</p>
                {ajustar ? (
                  <p>
                    Esta carga tem <b>{fmt(dividirModal.peso)} kg</b>. Digite quanto ela deve levar; a diferença
                    sai ou entra na outra parte.
                  </p>
                ) : (
                  <p>
                    Peso desta carga: <b>{fmt(dividirModal.peso)} kg</b>. A nova parte fica na mesma coluna —
                    depois arraste para o outro caminhão.
                  </p>
                )}
                <label className="block">
                  <span className="text-xs text-muted-foreground">
                    {ajustar ? "Peso nesta carga (kg)" : "Peso da nova parte (kg)"}
                  </span>
                  <input
                    type="number"
                    min={1}
                    step="0.1"
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
                {ajustar && outras.length > 1 && (
                  <label className="block">
                    <span className="text-xs text-muted-foreground">A diferença vai para</span>
                    <select
                      className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2"
                      value={contra?.id ?? ""}
                      onChange={(e) => setContrapartida(e.target.value)}
                    >
                      {outras.map((o) => (
                        <option key={o.id} value={o.id}>
                          Parte {o.parte || "?"} · {o.coluna} · {fmt(o.peso)} kg
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {valor > 0 && restante >= 0 && (
                  <div className="rounded-md bg-muted/50 px-3 py-2 text-xs space-y-0.5">
                    {ajustar ? (
                      <>
                        <div>Esta carga: <b>{fmt(valor)} kg</b></div>
                        <div>
                          {contra ? `Parte ${contra.parte || "?"} (${contra.coluna})` : "Outra parte"}:{" "}
                          <b>{fmt(restante)} kg</b>
                          {restante === 0 && " — será juntada a esta"}
                        </div>
                      </>
                    ) : (
                      <div>
                        Fica <b>{fmt(restante)} kg</b> + <b>{fmt(valor)} kg</b>
                      </div>
                    )}
                  </div>
                )}
                {erroDividir && <p className="text-xs text-destructive">{erroDividir}</p>}
              </div>
            );
          })()}
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
              {dividindo ? "Salvando…" : dividirModal?.modo === "ajustar" ? "Ajustar" : "Dividir"}
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

      <Dialog open={!!repModal} onOpenChange={(o) => !o && !repSalvando && setRepModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>O representante liberou?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            <strong className="text-foreground">{repModal?.titulo}</strong> tem Dt. Produção futura. Só carregue em{" "}
            <strong className="text-foreground">{repModal?.destinoLabel}</strong> se o representante autorizou.
          </p>
          <label className="block text-sm">
            <span className="text-xs font-medium text-muted-foreground">Quem liberou</span>
            <input
              className="mt-1 w-full px-3 py-2 text-sm rounded-md border border-input bg-background"
              value={repQuem}
              onChange={(e) => setRepQuem(e.target.value)}
              placeholder={repModal?.representante || "Nome do representante"}
            />
          </label>
          {repErro && <p className="text-sm text-destructive">{repErro}</p>}
          <DialogFooter>
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md border"
              disabled={repSalvando}
              onClick={() => setRepModal(null)}
            >
              Ainda não
            </button>
            <button
              type="button"
              disabled={repSalvando}
              className="px-4 py-2 text-sm rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
              onClick={() => void confirmarRepresentante()}
            >
              {repSalvando ? "Carregando…" : "Sim, liberou — carregar"}
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
  dataRef = "",
  onMoveTo,
  onOpenAudit,
  onAntecipar,
  onDivisao,
  onExportRomaneio,
  exportingRomaneio,
  onHabilitarSegundaViagem,
  habilitandoSegundaViagem,
  viagensRetornoHabilitadas,
  metricasRetorno,
  isRetorno,
  veiculoBaseId,
  itensRetorno,
  fechado,
  onToggleFechar,
  equipe,
  onSalvarEquipe,
}: {
  id: string;
  title: string;
  icon: typeof Truck;
  rota: Roteirizacao["rotas"][0] | null;
  jornadaMax: number;
  items: CardPedido[];
  destinos: { id: string; label: string }[];
  variant?: "default" | "futuro" | "local" | "retorno";
  dataRef?: string;
  onMoveTo: (destino: string, pedido: CardPedido) => void;
  onOpenAudit: (numeroPedido: string) => void;
  onAntecipar?: (numeroPedido: string) => void;
  onDivisao?: AcoesDivisao;
  onExportRomaneio?: (caminhaoId: string) => Promise<void>;
  exportingRomaneio?: boolean;
  onHabilitarSegundaViagem?: (veiculoId: string) => Promise<void>;
  habilitandoSegundaViagem?: boolean;
  viagensRetornoHabilitadas?: string[];
  metricasRetorno?: Roteirizacao["metricas_retorno"];
  isRetorno?: boolean;
  veiculoBaseId?: string;
  itensRetorno?: CardPedido[];
  fechado?: boolean;
  onToggleFechar?: () => void;
  equipe?: EquipeVeiculo;
  onSalvarEquipe?: (e: EquipeVeiculo) => Promise<void>;
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
          {onToggleFechar && (
            <button
              type="button"
              onClick={onToggleFechar}
              title={
                fechado
                  ? "Caminhão fechado: a sugestão automática não mexe nele. Clique para reabrir."
                  : "Fechar caminhão: a sugestão automática não coloca nem tira nada dele."
              }
              className={cn(
                "shrink-0 rounded p-1 hover:bg-muted",
                fechado ? "text-amber-600" : "text-muted-foreground",
              )}
            >
              {fechado ? <Lock className="w-3.5 h-3.5" /> : <LockOpen className="w-3.5 h-3.5" />}
            </button>
          )}
          <span className="text-xs text-muted-foreground shrink-0">{items.length}</span>
        </div>
        {fechado && (
          <div className="mt-1 text-[11px] font-medium text-amber-700">Fechado — a sugestão não mexe</div>
        )}
        {onSalvarEquipe && <EquipeEditor equipe={equipe} onSalvar={onSalvarEquipe} />}
        {variant === "futuro" && (
          <div className="mt-1 text-[11px] text-muted-foreground">
            Já pode carregar se o representante liberar — arraste para o caminhão
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
        {items.map((pedido, idx) => (
          <div key={`${id}::${getCardId(pedido)}`} className="space-y-2">
          {variant === "futuro" &&
            String(pedido.representante ?? "") !== String(items[idx - 1]?.representante ?? "\u0000") && (
              <GrupoRepresentante
                rep={String(pedido.representante ?? "") || "NÃO IDENTIFICADO"}
                linhas={items.filter((p) => String(p.representante ?? "") === String(pedido.representante ?? ""))}
                dataRef={dataRef}
              />
            )}
          <PedidoKanbanCard
            key={`${id}::${getCardId(pedido)}`}
            pedido={pedido}
            columnId={id}
            destinos={destinos}
            variant={variant}
            onMoveTo={(dest) => onMoveTo(dest, pedido)}
            onOpenAudit={onOpenAudit}
            onAntecipar={onAntecipar}
            onDivisao={
              onDivisao
                ? {
                    dividir: () => onDivisao.dividir(pedido),
                    ajustar: () => onDivisao.ajustar(pedido),
                    juntar: () => onDivisao.juntar(pedido),
                    confirmar: () => onDivisao.confirmar(pedido),
                  }
                : undefined
            }
          />
          </div>
        ))}
        {items.length === 0 && (
          <div className="text-xs text-center text-muted-foreground py-8 border border-dashed rounded-lg">
            Arraste pedidos aqui
          </div>
        )}
      </div>
      {itensRetorno && rota && (
        <SegundaViagem
          veiculoId={id}
          itens={itensRetorno}
          metricas={metricasRetorno?.[id]}
          destinos={destinos}
          onMoveTo={onMoveTo}
          onOpenAudit={onOpenAudit}
          onDivisao={onDivisao}
          onExportRomaneio={onExportRomaneio}
        />
      )}
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

/** Cabeçalho de representante na coluna "Consultar representante". */
function GrupoRepresentante({ rep, linhas, dataRef }: { rep: string; linhas: CardPedido[]; dataRef: string }) {
  const paraMensagem = linhas.map((p) => {
    const raw = p as Record<string, string>;
    return {
      cliente: String(p.cliente ?? ""),
      numero_pedido: String(p.numero_pedido ?? ""),
      of_ano: raw.of_ano ?? "",
      peso_kg: Number(p.peso_kg ?? 0),
      data_producao: raw.data_producao ?? "",
    };
  });
  const total = paraMensagem.reduce((s, l) => s + l.peso_kg, 0);
  return (
    <div className="mt-1 flex items-center justify-between gap-2 rounded-md bg-muted/60 px-2 py-1.5">
      <div className="min-w-0">
        <div className="truncate text-[11px] font-semibold">{rep}</div>
        <div className="text-[10px] text-muted-foreground">
          {linhas.length} {linhas.length === 1 ? "linha" : "linhas"} · {kg(total)}
        </div>
      </div>
      <BotaoCopiar pequeno rotulo="Mensagem" texto={mensagemRepresentante(rep, paraMensagem, dataRef)} />
    </div>
  );
}

/** Prefere a área da 2ª viagem quando o ponteiro está sobre ela (fica dentro do card do caminhão). */
const colisao: CollisionDetection = (args) => {
  const sob = pointerWithin(args);
  if (sob.length) {
    const retorno = sob.find((c) => String(c.id).endsWith(SUFIXO_VIAGEM_RETORNO));
    return retorno ? [retorno] : sob;
  }
  return rectIntersection(args);
};

/** 2ª viagem (tarde) dentro do mesmo card do caminhão, separada por uma faixa. */
function SegundaViagem({
  veiculoId,
  itens,
  metricas,
  destinos,
  onMoveTo,
  onOpenAudit,
  onDivisao,
  onExportRomaneio,
}: {
  veiculoId: string;
  itens: CardPedido[];
  metricas?: NonNullable<Roteirizacao["metricas_retorno"]>[string];
  destinos: { id: string; label: string }[];
  onMoveTo: (destino: string, pedido: CardPedido) => void;
  onOpenAudit: (numeroPedido: string) => void;
  onDivisao?: AcoesDivisao;
  onExportRomaneio?: (caminhaoId: string) => Promise<void>;
}) {
  const idRetorno = idRetornoVeiculo(veiculoId);
  const { setNodeRef, isOver } = useDroppable({ id: idRetorno, data: { columnId: idRetorno } });
  const peso = Number(metricas?.peso_alocado_kg ?? itens.reduce((s, p) => s + Number(p.peso_kg ?? 0), 0));
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "border-t-2 border-dashed border-success/50 bg-success/5 rounded-b-xl",
        isOver && "ring-2 ring-success bg-success/10",
      )}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <Truck className="w-4 h-4 text-success" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold">2ª viagem · tarde</div>
          <div className="text-[11px] text-muted-foreground">
            {itens.length} {itens.length === 1 ? "pedido" : "pedidos"} · {peso.toLocaleString("pt-BR")} kg
            {metricas?.teo_hhmm ? ` · TEO ${metricas.teo_hhmm}` : ""} · romaneio próprio
          </div>
        </div>
        {onExportRomaneio && (
          <button
            type="button"
            onClick={() => void onExportRomaneio(idRetorno)}
            title="Exportar romaneio da 2ª viagem"
            className="shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-md border bg-background text-muted-foreground hover:text-foreground"
          >
            <Download className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      <div className="p-2 pt-0 space-y-2 overflow-y-auto max-h-[400px]">
        {itens.map((pedido) => (
          <PedidoKanbanCard
            key={`${idRetorno}::${getCardId(pedido)}`}
            pedido={pedido}
            columnId={idRetorno}
            destinos={destinos}
            variant="retorno"
            onMoveTo={(dest) => onMoveTo(dest, pedido)}
            onOpenAudit={onOpenAudit}
            onDivisao={
              onDivisao
                ? {
                    dividir: () => onDivisao.dividir(pedido),
                    ajustar: () => onDivisao.ajustar(pedido),
                    juntar: () => onDivisao.juntar(pedido),
                    confirmar: () => onDivisao.confirmar(pedido),
                  }
                : undefined
            }
          />
        ))}
        {itens.length === 0 && (
          <div className="text-xs text-center text-muted-foreground py-5 border border-dashed border-success/40 rounded-lg">
            Arraste aqui os pedidos da 2ª viagem
          </div>
        )}
      </div>
    </div>
  );
}
