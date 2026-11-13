import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  rectIntersection,
  useDraggable,
  useDroppable,
  type CollisionDetection,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Download,
  GripVertical,
  Inbox,
  ListChecks,
  Loader2,
  Lock,
  LockOpen,
  MapPin,
  MapPinOff,
  MoreHorizontal,
  PackageSearch,
  PhoneCall,
  Truck,
  X,
} from "lucide-react";
import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import { PedidoAuditSheet } from "@/components/logistica/PedidoAuditSheet";
import {
  ItensAcoesParada,
  LinhaAgenda,
  PedidoKanbanCard,
  getCardId,
  type AcoesParada,
  type CardPedido,
} from "@/components/logistica/PedidoKanbanCard";
import { VehicleMetrics } from "@/components/logistica/VehicleMetrics";
import { BotaoCopiar } from "@/components/BotaoCopiar";
import { kg, mensagemRepresentante } from "@/lib/mensagens";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
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
  type AgendaParada,
  type PainelVeiculo,
  type Roteirizacao,
  type PedidoConsolidado,
} from "@/lib/logistica-types";
import { cn } from "@/lib/utils";
import { casaBusca, checklist, corDoCaminhao, paradas, type Parada } from "@/lib/montagem";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type PendingMove = {
  /** Uma ou várias cargas (seleção múltipla / parada inteira) */
  ids: string[];
  origem: string;
  destino: string;
  forcar?: boolean;
  liberarRepresentante?: boolean;
  autorizadoPor?: string;
};

export type MoverLoteFn = (payload: {
  ids: string[];
  destino: string;
  motivo?: string;
  forcar?: boolean;
  liberar_representante?: boolean;
  autorizado_por?: string;
}) => Promise<void>;

const pendenciasDoCard = (p: CardPedido): string[] =>
  String((p as Record<string, string>).pendencias ?? "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

/** Comercial e peso zerado não sobem no caminhão: ficam na página Pendências. */
const cardTravado = (p: CardPedido) =>
  pendenciasDoCard(p).some((x) => x === "PAGAMENTO_ANTECIPADO" || x === "PESO_ZERADO");

const COLUNAS_NAO_VEICULO = new Set([
  COLUMN_BACKLOG,
  COLUMN_BACKLOG_FUTURO,
  COLUMN_BACKLOG_LOCAL,
  COLUMN_COLETAS,
]);

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
    if (
      valor.motorista !== atual.motorista ||
      valor.ajudante !== atual.ajudante ||
      valor.placa !== atual.placa
    ) {
      void onSalvar(valor);
    }
  };
  const campo = (k: keyof EquipeVeiculo, rotulo: string) => (
    <input
      className="w-full rounded border border-input bg-background px-1.5 py-0.5 text-[11px] uppercase"
      placeholder={rotulo}
      title={rotulo}
      list={
        k === "motorista"
          ? "lista-motoristas"
          : k === "ajudante"
            ? "lista-ajudantes"
            : "lista-placas"
      }
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
  onNaoSaiu,
  onEquipe,
  onExportRomaneio,
  onHabilitarSegundaViagem,
  exportingCaminhaoId,
  habilitandoSegundaViagemId,
  warning,
  consolidadosByPedido = {},
  onMoverLote,
  onDesfazer,
  onOtimizarVeiculo,
  onVerMapa,
  busca = "",
  compacto = false,
  onOrdem,
  onHorarioCliente,
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
  onNaoSaiu?: (veiculoId: string, naoSaiu: boolean) => Promise<void>;
  onEquipe?: (veiculoId: string, equipe: EquipeVeiculo) => Promise<void>;
  onExportRomaneio?: (caminhaoId: string) => Promise<void>;
  onHabilitarSegundaViagem?: (veiculoId: string) => Promise<void>;
  exportingCaminhaoId?: string | null;
  habilitandoSegundaViagemId?: string | null;
  warning?: string;
  consolidadosByPedido?: Record<string, PedidoConsolidado>;
  onMoverLote?: MoverLoteFn;
  onDesfazer?: () => void;
  onOtimizarVeiculo?: (veiculoId: string) => Promise<void>;
  /** Abre o mapa (para localizar / conferir paradas) */
  onVerMapa?: () => void;
  /** Texto da busca: destaca os cards que casam */
  busca?: string;
  /** Mapa ao lado: colunas mais estreitas */
  compacto?: boolean;
  /** Ordem de entrega escolhida à mão (chaves cliente|cidade) */
  onOrdem?: (veiculoId: string, chaves: string[]) => Promise<void>;
  onHorarioCliente?: (clienteCodigo: string, horario: string) => Promise<void>;
}) {
  const [horarioModal, setHorarioModal] = useState<{
    codigo: string;
    nome: string;
    atual: string;
    origem: string;
  } | null>(null);
  const [horarioTexto, setHorarioTexto] = useState("");
  const [horarioErro, setHorarioErro] = useState("");
  const [activeCard, setActiveCard] = useState<CardPedido | null>(null);
  const [arrastando, setArrastando] = useState<{ ids: string[]; peso: number } | null>(null);
  const [selecionados, setSelecionados] = useState<Set<string>>(new Set());
  // Abre na primeira aba de "A alocar" que tem alguma coisa
  const [aba, setAba] = useState<string>(() =>
    data.backlog.length
      ? COLUMN_BACKLOG
      : (data.backlog_futuro ?? []).some((b) => !cardTravado(b))
        ? COLUMN_BACKLOG_FUTURO
        : (data.backlog_local ?? []).length
          ? COLUMN_BACKLOG_LOCAL
          : COLUMN_BACKLOG,
  );
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
  const [repModal, setRepModal] = useState<
    (PendingMove & { titulo: string; representante: string; destinoLabel: string }) | null
  >(null);
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
      {
        id: COLUMN_BACKLOG,
        label: "Sobras / Fila de espera",
        rota: null,
        icon: Inbox,
        variant: "default" as const,
      },
      ...vehicleCols,
      {
        id: COLUMN_BACKLOG_LOCAL,
        label: "Fila de Entregas Locais",
        rota: null,
        icon: MapPin,
        variant: "local" as const,
      },
      {
        id: COLUMN_COLETAS,
        label: "Coletas",
        rota: null,
        icon: PackageSearch,
        variant: "default" as const,
      },
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
      .sort(
        (a, b) =>
          String(a.representante ?? "").localeCompare(String(b.representante ?? "")) ||
          String(a.cliente ?? "").localeCompare(String(b.cliente ?? "")),
      );
    map[COLUMN_BACKLOG_LOCAL] = [...(data.backlog_local ?? [])];
    map[COLUMN_BACKLOG] = [...data.backlog];
    map[COLUMN_COLETAS] = [...(data.coletas ?? [])];
    return map;
  }, [columns, data]);

  const travados = useMemo(
    () => (data.backlog_futuro ?? []).filter(cardTravado),
    [data.backlog_futuro],
  );

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
      if (move.ids.length > 1 && onMoverLote) {
        await onMoverLote({
          ids: move.ids,
          destino: move.destino,
          motivo: move.motivo,
          forcar: move.forcar,
          liberar_representante: move.liberarRepresentante,
          autorizado_por: move.autorizadoPor,
        });
      } else {
        await onMove({
          numero_pedido: move.ids[0],
          destino: move.destino,
          motivo: move.motivo,
          forcar: move.forcar,
          liberar_representante: move.liberarRepresentante,
          autorizado_por: move.autorizadoPor,
        });
      }
      setBacklogModal(null);
      setForceModal(null);
      setSelecionados(new Set());
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

  /** Onde está cada carga (coluna) — para mover a seleção vinda de colunas diferentes. */
  const ondeEsta = useMemo(() => {
    const m: Record<string, { coluna: string; card: CardPedido }> = {};
    for (const [coluna, items] of Object.entries(itemsByColumn)) {
      for (const card of items) m[getCardId(card)] = { coluna, card };
    }
    return m;
  }, [itemsByColumn]);

  const requestMove = (idsBrutos: string[], origem: string, destino: string) => {
    const ids = idsBrutos.filter((id) => (ondeEsta[id]?.coluna ?? origem) !== destino);
    if (!ids.length) return;
    if (destino === COLUMN_BACKLOG) {
      setMotivo(MOTIVOS_BACKLOG[0]);
      setBacklogModal({ ids, origem, destino });
      return;
    }
    if (!COLUNAS_NAO_VEICULO.has(destino)) {
      const cards = ids.map((id) => ondeEsta[id]?.card).filter(Boolean) as CardPedido[];
      const comRep = cards.filter((c) => pendenciasDoCard(c).includes("CONSULTA_REPRESENTANTE"));
      if (comRep.length) {
        const reps = [...new Set(comRep.map((c) => String(c.representante ?? "")).filter(Boolean))];
        const rep = reps.join(" / ");
        setRepQuem(rep);
        setRepErro("");
        setRepModal({
          ids,
          origem,
          destino,
          titulo:
            comRep.length === 1
              ? tituloCard(comRep[0])
              : `${comRep.length} linhas de ${rep || "representantes"}`,
          representante: rep,
          destinoLabel: destinos.find((c) => c.id === destino)?.label ?? destino,
        });
        return;
      }
    }
    void executeMove({ ids, origem, destino });
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
          out.push({
            id: getCardId(p),
            peso: Number(p.peso_kg ?? 0),
            parte: String(raw.parte ?? ""),
            coluna: col.label,
          });
        }
      }
    }
    return out;
  };

  const confirmarDivisao = async () => {
    if (!dividirModal) return;
    const valor = Number(pesoDividir);
    const outras = partesDaLinha(dividirModal.idItem).filter((p) => p.id !== dividirModal.id);
    const contra =
      outras.find((p) => p.id === contrapartida) ?? [...outras].sort((a, b) => b.peso - a.peso)[0];
    const limite =
      dividirModal.modo === "dividir" ? dividirModal.peso : dividirModal.peso + (contra?.peso ?? 0);
    const invalido =
      dividirModal.modo === "dividir"
        ? !(valor > 0) || valor >= limite
        : !(valor > 0) || valor > limite;
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
              body: {
                id_carga: dividirModal.id,
                peso_kg: valor,
                id_carga_contrapartida: contra?.id ?? "",
              },
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

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  const pesoDe = (ids: string[]) =>
    ids.reduce((s, id) => s + Number(ondeEsta[id]?.card.peso_kg ?? 0), 0);

  const handleDragStart = (event: DragStartEvent) => {
    const payload = event.active.data.current as
      | { pedido?: CardPedido; ids?: string[] }
      | undefined;
    let ids = payload?.ids ?? (payload?.pedido ? [getCardId(payload.pedido)] : []);
    // arrastar um card selecionado leva a seleção inteira
    if (ids.length === 1 && selecionados.has(ids[0]) && selecionados.size > 1)
      ids = [...selecionados];
    setActiveCard(ids.length === 1 ? (payload?.pedido ?? null) : null);
    setArrastando({ ids, peso: pesoDe(ids) });
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const ids = arrastando?.ids ?? [];
    setActiveCard(null);
    setArrastando(null);
    const { active, over } = event;
    if (!over || !ids.length) return;
    const activeData = active.data.current as { columnId: string } | undefined;
    if (!activeData) return;

    let destino = String(over.id);
    if (destino.includes("::") && !destino.endsWith(SUFIXO_VIAGEM_RETORNO)) {
      destino = destino.split("::")[0];
    }
    requestMove(ids, activeData.columnId, destino);
  };

  // ---------------------------------------------------------------- seleção e teclado
  const alternarSelecao = (ids: string[]) =>
    setSelecionados((prev) => {
      const novo = new Set(prev);
      const todos = ids.every((id) => novo.has(id));
      for (const id of ids) {
        if (todos) novo.delete(id);
        else novo.add(id);
      }
      return novo;
    });

  // Seleção some quando o card sai do quadro (outro PC, desfazer…)
  useEffect(() => {
    setSelecionados((prev) => {
      const novo = new Set([...prev].filter((id) => ondeEsta[id]));
      return novo.size === prev.size ? prev : novo;
    });
  }, [ondeEsta]);

  const caminhoes = data.rotas.filter(
    (r) => !(data.veiculos_nao_sairam ?? []).includes(r.veiculo_id),
  );
  const moverSelecao = (destino: string) => {
    if (!selecionados.size) return;
    requestMove([...selecionados], "", destino);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement | null;
      if (
        alvo &&
        (alvo.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(alvo.tagName))
      )
        return;
      if (document.querySelector("[role=dialog]")) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        if (onDesfazer) {
          e.preventDefault();
          onDesfazer();
        }
        return;
      }
      if (e.key === "Escape") {
        setSelecionados(new Set());
        return;
      }
      if (!selecionados.size || e.ctrlKey || e.metaKey || e.altKey) return;
      if (/^[1-9]$/.test(e.key)) {
        const r = caminhoes[Number(e.key) - 1];
        if (r) {
          e.preventDefault();
          moverSelecao(r.veiculo_id);
        }
      } else if (e.key.toLowerCase() === "f") {
        e.preventDefault();
        moverSelecao(COLUMN_BACKLOG);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ---------------------------------------------------------------- busca
  const achados = useMemo(() => {
    const set = new Set<string>();
    if (!busca.trim()) return set;
    for (const [id, { card }] of Object.entries(ondeEsta)) if (casaBusca(card, busca)) set.add(id);
    return set;
  }, [busca, ondeEsta]);
  const destaqueDe = (id: string): "achou" | "apagado" | undefined =>
    busca.trim() ? (achados.has(id) ? "achou" : "apagado") : undefined;

  // busca acha algo só em outra aba de "A alocar": troca de aba
  useEffect(() => {
    if (!achados.size) return;
    const naAba = (col: string) =>
      (itemsByColumn[col] ?? []).some((c) => achados.has(getCardId(c)));
    if (naAba(aba)) return;
    const outra = ABAS_ALOCAR.find((a) => naAba(a.id));
    if (outra) setAba(outra.id);
  }, [achados]); // eslint-disable-line react-hooks/exhaustive-deps

  const propsCard = (id: string) => ({
    selecionado: selecionados.has(id),
    onSelecionar: () => alternarSelecao([id]),
    destaque: destaqueDe(id),
    idsArrasto: selecionados.has(id) && selecionados.size > 1 ? [...selecionados] : [id],
  });

  const acoesDivisao = onDivisao
    ? {
        dividir: (p: CardPedido) => abrirDivisao(p, "dividir"),
        ajustar: (p: CardPedido) => abrirDivisao(p, "ajustar"),
        juntar: (p: CardPedido) => void operar({ op: "juntar", body: { id_carga: getCardId(p) } }),
        confirmar: (p: CardPedido) =>
          void operar({ op: "confirmar", body: { id_carga: getCardId(p) } }),
      }
    : undefined;

  return (
    <>
      <div className="mb-3 space-y-2">
        {pendentesDivisao > 0 && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
            <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600" />
            <span>
              {pendentesDivisao === 1 ? "1 linha dividida" : `${pendentesDivisao} linhas divididas`}{" "}
              automaticamente por excesso de peso — confira no menu ⋯ do card (<b>Ajustar</b>,{" "}
              <b>Juntar</b> ou <b>Confirmar</b>).
            </span>
          </div>
        )}
        {travados.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-sm">
            <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600" />
            <span>
              {travados.length === 1 ? "1 linha travada" : `${travados.length} linhas travadas`}{" "}
              (comercial ou peso zerado,{" "}
              {kg(travados.reduce((s, b) => s + Number(b.peso_kg ?? 0), 0))}) — fora do quadro até
              resolver.
            </span>
            <Link to="/pendencias" className="font-semibold text-accent underline">
              Abrir Pendências
            </Link>
          </div>
        )}
        {warning && (
          <div className="flex items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            {warning}
          </div>
        )}
        {loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin" /> Atualizando…
          </div>
        )}
      </div>

      <datalist id="lista-motoristas">
        {(data.equipe_nomes?.motoristas ?? []).map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
      <datalist id="lista-ajudantes">
        {(data.equipe_nomes?.ajudantes ?? []).map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
      <datalist id="lista-placas">
        {(data.equipe_nomes?.placas ?? []).map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>

      <DndContext
        sensors={sensors}
        collisionDetection={colisao}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragCancel={() => {
          setActiveCard(null);
          setArrastando(null);
        }}
      >
        <TooltipProvider delayDuration={200}>
          <div className="flex items-start gap-4">
            {/* ---------------- A alocar (fila, representante, locais, coletas) */}
            <aside
              className={cn(
                "sticky top-2 flex shrink-0 flex-col rounded-xl border bg-card",
                compacto ? "w-[250px]" : "w-[300px]",
              )}
            >
              <div className="border-b px-3 pt-3 pb-2">
                <div className="text-sm font-semibold">A alocar</div>
                <div className="mt-2 grid grid-cols-2 gap-1">
                  {ABAS_ALOCAR.map((a) => (
                    <AbaAlocar
                      key={a.id}
                      id={a.id}
                      label={a.label}
                      icon={a.icon}
                      qtd={(itemsByColumn[a.id] ?? []).length}
                      achados={
                        (itemsByColumn[a.id] ?? []).filter((c) => achados.has(getCardId(c))).length
                      }
                      ativa={aba === a.id}
                      onClick={() => setAba(a.id)}
                    />
                  ))}
                </div>
              </div>
              {(() => {
                const col = columns.find((c) => c.id === aba) ?? columns[0];
                return (
                  <KanbanColumn
                    key={col.id}
                    id={col.id}
                    title={col.label}
                    icon={col.icon}
                    rota={null}
                    jornadaMax={jornadaMax}
                    items={itemsByColumn[col.id] ?? []}
                    destinos={destinos}
                    variant={col.variant}
                    embutida
                    propsCard={propsCard}
                    alternarSelecao={alternarSelecao}
                    dataRef={Object.values(consolidadosByPedido)[0]?.data_referencia ?? ""}
                    onMoveTo={(destino, pedido) =>
                      requestMove([getCardId(pedido)], col.id, destino)
                    }
                    onOpenAudit={setAuditPedidoId}
                    onAntecipar={col.variant === "futuro" ? setAnteciparModal : undefined}
                    onDivisao={acoesDivisao}
                  />
                );
              })()}
            </aside>

            {/* ---------------- Caminhões */}
            <div className="flex min-w-0 flex-1 items-start gap-3 overflow-x-auto pb-4">
              {data.rotas.map((rota, indice) => {
                const vid = rota.veiculo_id;
                const itens = itemsByColumn[vid] ?? [];
                return (
                  <ColunaCaminhao
                    key={vid}
                    rota={rota}
                    cor={corDoCaminhao(indice)}
                    atalho={caminhoes.findIndex((r) => r.veiculo_id === vid) + 1}
                    painel={data.painel_veiculos?.[vid]}
                    equipe={data.equipe_por_veiculo?.[vid]}
                    itens={itens}
                    jornadaMax={jornadaMax}
                    destinos={destinos}
                    fechado={(data.veiculos_fechados ?? []).includes(vid)}
                    naoSaiu={(data.veiculos_nao_sairam ?? []).includes(vid)}
                    onToggleFechar={
                      onFecharVeiculo
                        ? () =>
                            void onFecharVeiculo(vid, !(data.veiculos_fechados ?? []).includes(vid))
                        : undefined
                    }
                    onToggleNaoSaiu={
                      onNaoSaiu
                        ? () => void onNaoSaiu(vid, !(data.veiculos_nao_sairam ?? []).includes(vid))
                        : undefined
                    }
                    onSalvarEquipe={onEquipe ? (e: EquipeVeiculo) => onEquipe(vid, e) : undefined}
                    onExportRomaneio={onExportRomaneio}
                    exportingRomaneio={exportingCaminhaoId === vid}
                    onHabilitarSegundaViagem={
                      rota.segunda_viagem_elegivel &&
                      !data.viagens_retorno_habilitadas?.includes(vid)
                        ? onHabilitarSegundaViagem
                        : undefined
                    }
                    habilitandoSegundaViagem={habilitandoSegundaViagemId === vid}
                    onOtimizar={onOtimizarVeiculo ? () => onOtimizarVeiculo(vid) : undefined}
                    onVerMapa={onVerMapa}
                    onAplicarSugestao={(ids, destino) => requestMove(ids, vid, destino)}
                    onMoveTo={(destino, pedido) => requestMove([getCardId(pedido)], vid, destino)}
                    onOpenAudit={setAuditPedidoId}
                    onDivisao={acoesDivisao}
                    propsCard={propsCard}
                    alternarSelecao={alternarSelecao}
                    selecionados={selecionados}
                    destaqueDe={destaqueDe}
                    compacto={compacto}
                    onOrdem={onOrdem ? (chaves: string[]) => onOrdem(vid, chaves) : undefined}
                    onAbrirHorario={
                      onHorarioCliente
                        ? (codigo: string, nome: string, atual: string, origem: string) => {
                            setHorarioModal({ codigo, nome, atual, origem });
                            setHorarioTexto(origem === "cliente" ? atual.replace("–", " às ") : "");
                            setHorarioErro("");
                          }
                        : undefined
                    }
                  >
                    {data.viagens_retorno_habilitadas?.includes(vid) && (
                      <SegundaViagem
                        veiculoId={vid}
                        itens={itemsByColumn[idRetornoVeiculo(vid)] ?? []}
                        metricas={data.metricas_retorno?.[vid]}
                        destinos={destinos}
                        onMoveTo={(destino, pedido) =>
                          requestMove([getCardId(pedido)], idRetornoVeiculo(vid), destino)
                        }
                        onOpenAudit={setAuditPedidoId}
                        onDivisao={acoesDivisao}
                        onExportRomaneio={onExportRomaneio}
                        propsCard={propsCard}
                      />
                    )}
                  </ColunaCaminhao>
                );
              })}
            </div>
          </div>
        </TooltipProvider>
        <DragOverlay>
          {arrastando && arrastando.ids.length > 1 ? (
            <div className="w-[260px] rounded-lg border-2 border-accent bg-card px-3 py-2 text-sm font-semibold shadow-lg">
              {arrastando.ids.length} cargas · {kg(arrastando.peso)}
            </div>
          ) : activeCard ? (
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

      {selecionados.size > 0 && (
        <div className="fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 flex-wrap items-center gap-2 rounded-xl border bg-card px-4 py-2.5 text-sm shadow-xl">
          <span className="font-semibold">
            {selecionados.size} {selecionados.size === 1 ? "selecionada" : "selecionadas"} ·{" "}
            {kg(pesoDe([...selecionados]))}
          </span>
          <span className="text-muted-foreground">Mover para:</span>
          {caminhoes.map((r, i) => (
            <button
              key={r.veiculo_id}
              type="button"
              onClick={() => moverSelecao(r.veiculo_id)}
              className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 hover:bg-muted"
              title={`Tecla ${i + 1}`}
            >
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ background: corDoCaminhao(data.rotas.indexOf(r)) }}
              />
              {data.painel_veiculos?.[r.veiculo_id]?.nome ?? r.veiculo_nome}
              <kbd className="rounded bg-muted px-1 text-[10px] text-muted-foreground">{i + 1}</kbd>
            </button>
          ))}
          <button
            type="button"
            onClick={() => moverSelecao(COLUMN_BACKLOG)}
            className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 hover:bg-muted"
            title="Tecla F"
          >
            Fila <kbd className="rounded bg-muted px-1 text-[10px] text-muted-foreground">F</kbd>
          </button>
          <button
            type="button"
            onClick={() => setSelecionados(new Set())}
            className="text-muted-foreground underline hover:text-foreground"
            title="Tecla Esc"
          >
            Limpar
          </button>
        </div>
      )}

      <Dialog open={!!backlogModal} onOpenChange={(o) => !o && setBacklogModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Por que vai para a fila?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {backlogModal && backlogModal.ids.length > 1 ? (
              <>
                <strong>{backlogModal.ids.length} cargas</strong> vão para a fila de espera.
              </>
            ) : (
              <>
                <strong>
                  {backlogModal ? tituloCard(ondeEsta[backlogModal.ids[0]]?.card ?? {}) : ""}
                </strong>{" "}
                vai para a fila de espera.
              </>
            )}
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
              onClick={() => backlogModal && void executeMove({ ...backlogModal, motivo })}
            >
              Confirmar
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!dividirModal} onOpenChange={(o) => !o && setDividirModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dividirModal?.modo === "ajustar" ? "Ajustar divisão" : "Dividir carga"}
            </DialogTitle>
          </DialogHeader>
          {dividirModal &&
            (() => {
              const outras = partesDaLinha(dividirModal.idItem).filter(
                (p) => p.id !== dividirModal.id,
              );
              const contra =
                outras.find((p) => p.id === contrapartida) ??
                [...outras].sort((a, b) => b.peso - a.peso)[0];
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
                      Esta carga tem <b>{fmt(dividirModal.peso)} kg</b>. Digite quanto ela deve
                      levar; a diferença sai ou entra na outra parte.
                    </p>
                  ) : (
                    <p>
                      Peso desta carga: <b>{fmt(dividirModal.peso)} kg</b>. A nova parte fica na
                      mesma coluna — depois arraste para o outro caminhão.
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
                          <div>
                            Esta carga: <b>{fmt(valor)} kg</b>
                          </div>
                          <div>
                            {contra
                              ? `Parte ${contra.parte || "?"} (${contra.coluna})`
                              : "Outra parte"}
                            : <b>{fmt(restante)} kg</b>
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
              onClick={() => forceModal && void executeMove({ ...forceModal, forcar: true })}
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
            <strong className="text-foreground">{repModal?.titulo}</strong> tem Dt. Produção futura.
            Só carregue em <strong className="text-foreground">{repModal?.destinoLabel}</strong> se
            o representante autorizou.
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
            <span className="text-xs font-medium text-muted-foreground">
              Motivo do adiantamento *
            </span>
            <textarea
              className="mt-1 w-full min-h-[72px] px-3 py-2 text-sm rounded-md border border-input bg-background"
              value={motivoAdiantamento}
              onChange={(e) => setMotivoAdiantamento(e.target.value)}
              placeholder="Ex.: cliente confirmou recebimento antecipado"
            />
          </label>
          <label className="block text-sm">
            <span className="text-xs font-medium text-muted-foreground">
              Representante que autorizou
            </span>
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

      <Dialog open={!!horarioModal} onOpenChange={(o) => !o && setHorarioModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Horário de recebimento — {horarioModal?.nome}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Vale daqui para frente para este cliente (nos dois PCs). O horário escrito na observação
            do pedido continua valendo primeiro.
            {horarioModal?.atual && (
              <>
                {" "}
                Hoje está: <b className="text-foreground">{horarioModal.atual}</b> (
                {horarioModal.origem === "observacao"
                  ? "da observação"
                  : horarioModal.origem === "cliente"
                    ? "salvo no cliente"
                    : "padrão"}
                ).
              </>
            )}
          </p>
          <input
            autoFocus
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            placeholder="Ex.: 08:00 às 17:00"
            value={horarioTexto}
            onChange={(e) => {
              setHorarioTexto(e.target.value);
              setHorarioErro("");
            }}
          />
          {horarioErro && <p className="text-sm text-destructive">{horarioErro}</p>}
          <DialogFooter>
            {horarioModal?.origem === "cliente" && (
              <button
                type="button"
                className="mr-auto px-4 py-2 text-sm rounded-md border text-destructive"
                onClick={async () => {
                  if (!horarioModal || !onHorarioCliente) return;
                  await onHorarioCliente(horarioModal.codigo, "");
                  setHorarioModal(null);
                }}
              >
                Apagar (usar o padrão)
              </button>
            )}
            <button
              type="button"
              className="px-4 py-2 text-sm rounded-md border"
              onClick={() => setHorarioModal(null)}
            >
              Cancelar
            </button>
            <button
              type="button"
              disabled={!horarioTexto.trim()}
              className="px-4 py-2 text-sm rounded-md bg-primary text-primary-foreground disabled:opacity-50"
              onClick={async () => {
                if (!horarioModal || !onHorarioCliente) return;
                try {
                  await onHorarioCliente(horarioModal.codigo, horarioTexto.trim());
                  setHorarioModal(null);
                } catch (e) {
                  setHorarioErro(e instanceof Error ? e.message : "Não foi possível salvar.");
                }
              }}
            >
              Salvar
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
  naoSaiu,
  onToggleNaoSaiu,
  equipe,
  onSalvarEquipe,
  embutida,
  propsCard,
  alternarSelecao,
}: {
  embutida?: boolean;
  propsCard?: PropsCardFn;
  alternarSelecao?: (ids: string[]) => void;
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
  naoSaiu?: boolean;
  onToggleNaoSaiu?: () => void;
  equipe?: EquipeVeiculo;
  onSalvarEquipe?: (e: EquipeVeiculo) => Promise<void>;
}) {
  const { setNodeRef, isOver } = useDroppable({ id, data: { columnId: id } });
  // Representantes abertos (a aba "Representante" começa com todos fechados)
  const [abertos, setAbertos] = useState<Set<string>>(new Set());
  const cardDe = (pedido: CardPedido) => (
    <PedidoKanbanCard
      key={`${id}::${getCardId(pedido)}`}
      pedido={pedido}
      columnId={id}
      destinos={destinos}
      variant={variant}
      {...(propsCard?.(getCardId(pedido)) ?? {})}
      onMoveTo={(dest) => onMoveTo(dest, pedido)}
      onOpenAudit={onOpenAudit}
      onAntecipar={onAntecipar}
      onDivisao={divisaoDoCard(onDivisao, pedido)}
    />
  );

  const teoMin =
    isRetorno && veiculoBaseId
      ? parseInt(metricasRetorno?.[veiculoBaseId]?.teo_minutos ?? "0", 10)
      : parseInt(rota?.teo_minutos ?? rota?.tempo_total_min ?? "0", 10);
  const teoLabel =
    isRetorno && veiculoBaseId
      ? (metricasRetorno?.[veiculoBaseId]?.teo_hhmm ?? formatTeoMin(teoMin))
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
        embutida
          ? "flex flex-col rounded-b-xl"
          : "flex w-[300px] shrink-0 flex-col rounded-xl border",
        variant === "futuro" && "border-muted-foreground/30 bg-muted/15",
        variant === "local" && "border-emerald-500/30 bg-emerald-500/5",
        variant === "retorno" && "border-success/40 bg-success/5",
        variant === "default" && rota?.alerta_elastico && "border-warning/50 bg-warning/5",
        variant === "default" && !rota?.alerta_elastico && "border-border bg-muted/20",
        isOver && "ring-2 ring-accent bg-accent/5",
      )}
    >
      {embutida ? (
        (variant === "futuro" || variant === "local" || items.length > 0) && (
          <div className="px-3 pt-2 text-[11px] text-muted-foreground">
            {variant === "futuro"
              ? "Dt. Produção futura: carrega se o representante liberar — arraste para o caminhão."
              : variant === "local"
                ? "Americana, Santa Bárbara d'Oeste e SBO — 2ª viagem local."
                : `${items.length} ${items.length === 1 ? "linha" : "linhas"} · ${kg(items.reduce((s, p) => s + Number(p.peso_kg ?? 0), 0))}`}
          </div>
        )
      ) : (
        <div
          className={cn(
            "px-3 py-3 border-b border-border rounded-t-xl",
            variant === "futuro" ? "bg-muted/50" : "bg-card",
            variant === "local" && "bg-emerald-500/10",
            variant === "retorno" && "bg-success/10",
          )}
        >
          <div className="flex items-center gap-2">
            <Icon
              className={cn(
                "w-4 h-4",
                variant === "futuro" && "text-muted-foreground",
                variant === "local" && "text-emerald-600",
                variant === "retorno" && "text-success",
                variant === "default" && "text-accent",
              )}
            />
            <div className="font-semibold text-sm truncate flex-1 min-w-0">{title}</div>
            {rota && <TeoBadge teoMin={teoMin} teoLabel={teoLabel} />}
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
          {naoSaiu ? (
            <div className="mt-2 rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-[11px] text-destructive">
              <b>NÃO SAIU</b> — a carga vai para a próxima rota quando o próximo dia for aberto.
              {onToggleNaoSaiu && (
                <button type="button" className="ml-1 underline" onClick={onToggleNaoSaiu}>
                  desfazer
                </button>
              )}
            </div>
          ) : (
            fechado && (
              <div className="mt-1 text-[11px] font-medium text-amber-700">
                Fechado — a sugestão não mexe
              </div>
            )
          )}
          {!naoSaiu && onToggleNaoSaiu && items.length > 0 && (
            <button
              type="button"
              onClick={() => {
                if (
                  window.confirm(
                    "Este caminhão não vai sair hoje? A carga volta para a próxima rota.",
                  )
                )
                  onToggleNaoSaiu();
              }}
              className="mt-1 text-[11px] text-muted-foreground underline hover:text-destructive"
            >
              Caminhão não saiu?
            </button>
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
              Peso:{" "}
              {(metricasRetorno?.[veiculoBaseId]?.peso_alocado_kg ?? 0).toLocaleString("pt-BR")} kg
            </div>
          )}
        </div>
      )}
      <div
        className={cn(
          "flex-1 p-2 space-y-2 overflow-y-auto",
          embutida ? "max-h-[68vh]" : "max-h-[560px]",
        )}
      >
        {variant === "futuro"
          ? gruposRepresentante(items).map(({ rep, linhas }) => {
              const ids = linhas.map(getCardId);
              const achou = ids.some((i) => propsCard?.(i).destaque === "achou");
              return (
                <GrupoRepresentante
                  key={rep}
                  columnId={id}
                  rep={rep}
                  linhas={linhas}
                  dataRef={dataRef}
                  aberto={abertos.has(rep) || achou}
                  onToggle={() =>
                    setAbertos((prev) => {
                      const novo = new Set(prev);
                      if (novo.has(rep)) novo.delete(rep);
                      else novo.add(rep);
                      return novo;
                    })
                  }
                  apagado={!!propsCard && ids.every((i) => propsCard(i).destaque === "apagado")}
                  achou={achou}
                  selecionados={ids.filter((i) => propsCard?.(i).selecionado).length}
                  onSelecionarTodos={alternarSelecao ? () => alternarSelecao(ids) : undefined}
                >
                  {linhas.map(cardDe)}
                </GrupoRepresentante>
              );
            })
          : items.map(cardDe)}
        {items.length === 0 && (
          <div className="text-xs text-center text-muted-foreground py-8 border border-dashed rounded-lg">
            {embutida ? "Vazio — solte cards aqui" : "Arraste pedidos aqui"}
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

/** Representantes na ordem da coluna, cada um com as suas linhas. */
function gruposRepresentante(items: CardPedido[]) {
  const grupos: { rep: string; linhas: CardPedido[] }[] = [];
  for (const p of items) {
    const rep = String(p.representante ?? "") || "NÃO IDENTIFICADO";
    const g = grupos.find((x) => x.rep === rep);
    if (g) g.linhas.push(p);
    else grupos.push({ rep, linhas: [p] });
  }
  return grupos;
}

/**
 * Caixa do representante na aba "Representante": fechada mostra nome, linhas e kg;
 * clique abre os pedidos. A alça arrasta todas as linhas dele de uma vez.
 */
function GrupoRepresentante({
  columnId,
  rep,
  linhas,
  dataRef,
  aberto,
  onToggle,
  apagado,
  achou,
  selecionados,
  onSelecionarTodos,
  children,
}: {
  columnId: string;
  rep: string;
  linhas: CardPedido[];
  dataRef: string;
  aberto: boolean;
  onToggle: () => void;
  apagado?: boolean;
  achou?: boolean;
  selecionados: number;
  onSelecionarTodos?: () => void;
  children: React.ReactNode;
}) {
  const ids = linhas.map(getCardId);
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `${columnId}::rep::${rep}`,
    data: { columnId, ids },
  });
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
  const todos = selecionados === linhas.length;
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "rounded-lg border bg-card",
        aberto && "border-accent/40",
        todos && "ring-2 ring-accent",
        achou && "ring-2 ring-amber-400",
        apagado && "opacity-35",
        isDragging && "opacity-50",
      )}
    >
      <div className="flex items-center gap-1.5 px-2 py-2">
        <button
          type="button"
          title="Arrastar todas as linhas deste representante"
          className="shrink-0 cursor-grab touch-none text-muted-foreground hover:text-foreground active:cursor-grabbing"
          {...listeners}
          {...attributes}
        >
          <GripVertical className="h-4 w-4" />
        </button>
        {onSelecionarTodos && (
          <input
            type="checkbox"
            aria-label={`Selecionar todas as linhas de ${rep}`}
            className="h-3.5 w-3.5 shrink-0 cursor-pointer"
            checked={todos}
            ref={(el) => {
              if (el) el.indeterminate = selecionados > 0 && !todos;
            }}
            onChange={onSelecionarTodos}
          />
        )}
        <button
          type="button"
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
        >
          {aberto ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <div className="min-w-0">
            <div className="break-words text-xs font-semibold leading-tight">{rep}</div>
            <div className="text-[11px] text-muted-foreground">
              {linhas.length} {linhas.length === 1 ? "linha" : "linhas"} · {kg(total)}
              {selecionados > 0 && !todos && ` · ${selecionados} selecionada(s)`}
            </div>
          </div>
        </button>
        <BotaoCopiar
          pequeno
          rotulo="Mensagem"
          texto={mensagemRepresentante(rep, paraMensagem, dataRef)}
        />
      </div>
      {aberto && <div className="space-y-2 border-t bg-muted/20 p-1.5">{children}</div>}
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
  propsCard,
}: {
  propsCard?: PropsCardFn;
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
  const peso = Number(
    metricas?.peso_alocado_kg ?? itens.reduce((s, p) => s + Number(p.peso_kg ?? 0), 0),
  );
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
            {itens.length} {itens.length === 1 ? "pedido" : "pedidos"} ·{" "}
            {peso.toLocaleString("pt-BR")} kg
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
            {...(propsCard?.(getCardId(pedido)) ?? {})}
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

// ====================================================================== tela nova (montagem v2)

const ABAS_ALOCAR: { id: string; label: string; icon: typeof Truck }[] = [
  { id: COLUMN_BACKLOG, label: "Fila", icon: Inbox },
  { id: COLUMN_BACKLOG_FUTURO, label: "Representante", icon: PhoneCall },
  { id: COLUMN_BACKLOG_LOCAL, label: "Locais", icon: MapPin },
  { id: COLUMN_COLETAS, label: "Coletas", icon: PackageSearch },
];

type PropsCardFn = (id: string) => {
  selecionado: boolean;
  onSelecionar: () => void;
  destaque?: "achou" | "apagado";
  idsArrasto: string[];
};

/** Aba de "A alocar" — também aceita card solto em cima dela. */
function AbaAlocar({
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

/** Coluna do caminhão: cabeçalho com resumo, checklist "pronto para sair" e as paradas na ordem de entrega. */
function ColunaCaminhao({
  rota,
  cor,
  atalho,
  painel,
  equipe,
  itens,
  jornadaMax,
  destinos,
  fechado,
  naoSaiu,
  onToggleFechar,
  onToggleNaoSaiu,
  onSalvarEquipe,
  onExportRomaneio,
  exportingRomaneio,
  onHabilitarSegundaViagem,
  habilitandoSegundaViagem,
  onOtimizar,
  onVerMapa,
  onAplicarSugestao,
  onMoveTo,
  onOpenAudit,
  onDivisao,
  propsCard,
  alternarSelecao,
  selecionados,
  destaqueDe,
  children,
  compacto,
  onOrdem,
  onAbrirHorario,
}: {
  compacto?: boolean;
  onOrdem?: (chaves: string[]) => Promise<void>;
  onAbrirHorario?: (codigo: string, nome: string, atual: string, origem: string) => void;
  rota: Roteirizacao["rotas"][0];
  cor: string;
  atalho: number;
  painel?: PainelVeiculo;
  equipe?: EquipeVeiculo;
  itens: CardPedido[];
  jornadaMax: number;
  destinos: { id: string; label: string }[];
  fechado: boolean;
  naoSaiu: boolean;
  onToggleFechar?: () => void;
  onToggleNaoSaiu?: () => void;
  onSalvarEquipe?: (e: EquipeVeiculo) => Promise<void>;
  onExportRomaneio?: (caminhaoId: string) => Promise<void>;
  exportingRomaneio?: boolean;
  onHabilitarSegundaViagem?: (veiculoId: string) => Promise<void>;
  habilitandoSegundaViagem?: boolean;
  onOtimizar?: () => Promise<void>;
  onVerMapa?: () => void;
  onAplicarSugestao: (ids: string[], destino: string) => void;
  onMoveTo: (destino: string, pedido: CardPedido) => void;
  onOpenAudit: (id: string) => void;
  onDivisao?: AcoesDivisao;
  propsCard: PropsCardFn;
  alternarSelecao: (ids: string[]) => void;
  selecionados: Set<string>;
  destaqueDe: (id: string) => "achou" | "apagado" | undefined;
  children?: React.ReactNode;
}) {
  const vid = rota.veiculo_id;
  const { setNodeRef, isOver } = useDroppable({ id: vid, data: { columnId: vid } });
  const [otimizando, setOtimizando] = useState(false);
  const [verChecklist, setVerChecklist] = useState(false);
  const lista = paradas(itens);
  const semLocal = new Set(painel?.sem_localizacao ?? []);
  const check = checklist(rota, painel, equipe, itens, jornadaMax);
  const teoMin = parseInt(rota.teo_minutos || rota.tempo_total_min || "0", 10) || 0;
  const nome = painel?.nome ?? rota.veiculo_nome;
  const pendentes = check.itens.filter((i) => !i.ok);
  const peso = Number(rota.peso_alocado_kg ?? 0);
  const agenda = painel?.agenda ?? null;
  const ordem = lista.map((p) => p.chave);
  const acoesDe = (p: Parada): AcoesParada => {
    const i = ordem.indexOf(p.chave);
    const trocar = (j: number) => {
      const nova = [...ordem];
      [nova[i], nova[j]] = [nova[j], nova[i]];
      return nova;
    };
    const primeira = p.linhas[0] as Record<string, unknown>;
    return {
      primeiro:
        onOrdem && i > 0
          ? () => void onOrdem([p.chave, ...ordem.filter((c) => c !== p.chave)])
          : undefined,
      subir: onOrdem && i > 0 ? () => void onOrdem(trocar(i - 1)) : undefined,
      descer: onOrdem && i < ordem.length - 1 ? () => void onOrdem(trocar(i + 1)) : undefined,
      horario:
        onAbrirHorario && primeira.cliente_codigo
          ? () =>
              onAbrirHorario(
                String(primeira.cliente_codigo),
                p.apelido || p.cliente,
                agenda?.paradas[p.chave]?.janela ?? "",
                agenda?.paradas[p.chave]?.origem_janela ?? "",
              )
          : undefined,
    };
  };

  const otimizar = async () => {
    if (!onOtimizar) return;
    setOtimizando(true);
    try {
      await onOtimizar();
    } finally {
      setOtimizando(false);
    }
  };

  const acaoChecklist = (acao?: string) => {
    if (acao === "otimizar" && onOtimizar)
      return (
        <button
          type="button"
          className="ml-auto shrink-0 font-semibold underline"
          disabled={otimizando}
          onClick={() => void otimizar()}
        >
          {otimizando ? "Otimizando…" : "Otimizar"}
        </button>
      );
    if (acao === "localizar" && onVerMapa)
      return (
        <button
          type="button"
          className="ml-auto shrink-0 font-semibold underline"
          onClick={onVerMapa}
        >
          Ver no mapa
        </button>
      );
    return null;
  };

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex shrink-0 flex-col rounded-xl border bg-muted/20",
        compacto ? "w-[300px]" : "w-[340px]",
        naoSaiu && "opacity-70",
        isOver && "ring-2 ring-accent bg-accent/5",
      )}
      style={{ borderTop: `4px solid ${cor}` }}
    >
      <div className="rounded-t-xl border-b bg-card px-3 pt-2.5 pb-2">
        <div className="flex items-center gap-2">
          <Truck className="h-4 w-4 shrink-0" style={{ color: cor }} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-bold" title={nome}>
              {nome}
              {equipe?.placa && (
                <span className="ml-1.5 font-mono text-xs font-semibold text-muted-foreground">
                  {equipe.placa}
                </span>
              )}
            </div>
            {equipe?.motorista && (
              <div className="truncate text-[11px] text-muted-foreground">{equipe.motorista}</div>
            )}
          </div>
          {atalho > 0 && (
            <kbd
              className="shrink-0 rounded bg-muted px-1.5 text-[10px] text-muted-foreground"
              title={`Com cards selecionados, a tecla ${atalho} manda para este caminhão`}
            >
              {atalho}
            </kbd>
          )}
          {onToggleFechar && (
            <button
              type="button"
              onClick={onToggleFechar}
              title={
                fechado
                  ? "Fechado: a sugestão automática não mexe nele. Clique para reabrir."
                  : "Fechar: a sugestão automática não coloca nem tira nada dele."
              }
              className={cn(
                "shrink-0 rounded p-1 hover:bg-muted",
                fechado ? "text-amber-600" : "text-muted-foreground",
              )}
            >
              {fechado ? <Lock className="h-3.5 w-3.5" /> : <LockOpen className="h-3.5 w-3.5" />}
            </button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted"
                aria-label="Mais ações"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {onOtimizar && (
                <DropdownMenuItem onClick={() => void otimizar()}>
                  Otimizar a ordem de entrega
                </DropdownMenuItem>
              )}
              {onExportRomaneio && (
                <DropdownMenuItem
                  disabled={exportingRomaneio}
                  onClick={() => void onExportRomaneio(vid)}
                >
                  Exportar romaneio deste caminhão
                </DropdownMenuItem>
              )}
              {onHabilitarSegundaViagem && (
                <DropdownMenuItem
                  disabled={habilitandoSegundaViagem}
                  onClick={() => void onHabilitarSegundaViagem(vid)}
                >
                  Habilitar 2ª viagem (tarde)
                </DropdownMenuItem>
              )}
              {onToggleNaoSaiu && itens.length > 0 && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive"
                    onClick={() => {
                      if (
                        naoSaiu ||
                        window.confirm(
                          "Este caminhão não vai sair hoje? A carga volta para a próxima rota.",
                        )
                      )
                        onToggleNaoSaiu();
                    }}
                  >
                    {naoSaiu ? "Desfazer “não saiu”" : "Caminhão não saiu…"}
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="mt-1.5 text-[11px] text-muted-foreground">
          <b className="text-foreground">{lista.length}</b>{" "}
          {lista.length === 1 ? "cliente" : "clientes"} ·{" "}
          <b className="text-foreground">{itens.length}</b>{" "}
          {itens.length === 1 ? "linha" : "linhas"} · <b className="text-foreground">{kg(peso)}</b>
          {agenda ? (
            <>
              {" "}
              · sai <b className="text-foreground">{agenda.saida}</b> · volta{" "}
              <b className="text-foreground">{agenda.volta}</b>
            </>
          ) : (
            rota.retorno_previsto && <> · volta {rota.retorno_previsto}</>
          )}
          {rota.regiao_predominante && <> · {rota.regiao_predominante}</>}
        </div>
        <div className="-mx-3 mt-1">
          <VehicleMetrics rota={rota} jornadaMax={jornadaMax} />
        </div>
        {onSalvarEquipe && <EquipeEditor equipe={equipe} onSalvar={onSalvarEquipe} />}

        {naoSaiu ? (
          <div className="mt-2 rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-[11px] text-destructive">
            <b>NÃO SAIU</b> — a carga vai para a próxima rota quando o próximo dia for aberto.
          </div>
        ) : (
          fechado && (
            <div className="mt-1.5 text-[11px] font-medium text-amber-700">
              Fechado — a sugestão automática não mexe
            </div>
          )
        )}

        {itens.length > 0 && !naoSaiu && (
          <div className="mt-2">
            {check.pronto ? (
              <div className="flex items-center gap-1.5 rounded-md bg-emerald-500/15 px-2 py-1 text-xs font-semibold text-emerald-700">
                <CheckCircle2 className="h-3.5 w-3.5" /> Pronto para sair
              </div>
            ) : (
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 text-[11px] text-amber-900">
                <button
                  type="button"
                  className="flex w-full items-center gap-1.5 px-2 py-1 font-semibold"
                  onClick={() => setVerChecklist((v) => !v)}
                >
                  <ListChecks className="h-3.5 w-3.5" />
                  Falta{pendentes.length > 1 ? "m" : ""} {pendentes.length} para sair
                  <span className="ml-auto font-normal underline">
                    {verChecklist ? "ocultar" : "ver"}
                  </span>
                </button>
                {(verChecklist || pendentes.length <= 3) && (
                  <ul className="space-y-0.5 px-2 pb-1.5">
                    {(verChecklist ? check.itens : pendentes).map((i) => (
                      <li
                        key={i.texto}
                        className={cn("flex items-center gap-1.5", i.ok && "text-emerald-700")}
                      >
                        {i.ok ? (
                          <Check className="h-3 w-3 shrink-0" />
                        ) : (
                          <X className="h-3 w-3 shrink-0 text-amber-700" />
                        )}
                        <span>{i.texto}</span>
                        {!i.ok && acaoChecklist(i.acao)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}

        {painel?.sugestao_corredor && (
          <div className="mt-2 flex items-start gap-1.5 rounded-md border border-warning/50 bg-warning/10 px-2 py-1.5 text-[11px]">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
            <span className="flex-1 leading-snug" title={rota.mensagem_alerta_elastico}>
              {painel.sugestao_corredor}
            </span>
            {!!painel.sugestao_ids?.length && painel.sugestao_destino && (
              <button
                type="button"
                className="shrink-0 font-semibold underline"
                onClick={() => onAplicarSugestao(painel.sugestao_ids!, painel.sugestao_destino!)}
              >
                Mover
              </button>
            )}
          </div>
        )}
      </div>

      <div className="max-h-[62vh] flex-1 space-y-1.5 overflow-y-auto p-2">
        {lista.map((p) =>
          p.linhas.length === 1 ? (
            <PedidoKanbanCard
              key={p.ids[0]}
              pedido={p.linhas[0]}
              columnId={vid}
              destinos={destinos}
              parada={p.numero}
              cor={cor}
              semLocal={semLocal.has(p.ids[0])}
              agendaParada={agenda?.paradas[p.chave]}
              acoesParada={acoesDe(p)}
              onMoveTo={(dest) => onMoveTo(dest, p.linhas[0])}
              onOpenAudit={onOpenAudit}
              onDivisao={divisaoDoCard(onDivisao, p.linhas[0])}
              {...propsCard(p.ids[0])}
            />
          ) : (
            <ParadaGrupo
              key={p.chave}
              parada={p}
              columnId={vid}
              cor={cor}
              destinos={destinos}
              semLocal={p.ids.some((id) => semLocal.has(id))}
              agendaParada={agenda?.paradas[p.chave]}
              acoesParada={acoesDe(p)}
              onMoveTo={onMoveTo}
              onOpenAudit={onOpenAudit}
              onDivisao={onDivisao}
              propsCard={propsCard}
              alternarSelecao={alternarSelecao}
              selecionados={selecionados}
              destaqueDe={destaqueDe}
            />
          ),
        )}
        {itens.length === 0 && (
          <div className="rounded-lg border border-dashed py-8 text-center text-xs text-muted-foreground">
            Arraste pedidos aqui
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

const divisaoDoCard = (onDivisao: AcoesDivisao | undefined, pedido: CardPedido) =>
  onDivisao
    ? {
        dividir: () => onDivisao.dividir(pedido),
        ajustar: () => onDivisao.ajustar(pedido),
        juntar: () => onDivisao.juntar(pedido),
        confirmar: () => onDivisao.confirmar(pedido),
      }
    : undefined;

/** Parada com várias linhas do mesmo cliente: um card só, que abre as linhas. Arrastar o cabeçalho leva todas. */
function ParadaGrupo({
  parada,
  columnId,
  cor,
  destinos,
  semLocal,
  onMoveTo,
  onOpenAudit,
  onDivisao,
  propsCard,
  alternarSelecao,
  selecionados,
  destaqueDe,
  agendaParada,
  acoesParada,
}: {
  agendaParada?: AgendaParada;
  acoesParada?: AcoesParada;
  parada: Parada;
  columnId: string;
  cor: string;
  destinos: { id: string; label: string }[];
  semLocal: boolean;
  onMoveTo: (destino: string, pedido: CardPedido) => void;
  onOpenAudit: (id: string) => void;
  onDivisao?: AcoesDivisao;
  propsCard: PropsCardFn;
  alternarSelecao: (ids: string[]) => void;
  selecionados: Set<string>;
  destaqueDe: (id: string) => "achou" | "apagado" | undefined;
}) {
  const [aberta, setAberta] = useState(false);
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `${columnId}::grupo::${parada.chave}`,
    data: { columnId, ids: parada.ids },
  });
  const primeira = parada.linhas[0] as Record<string, string>;
  const todasSel = parada.ids.every((id) => selecionados.has(id));
  const algumaSel = parada.ids.some((id) => selecionados.has(id));
  const destaques = parada.ids.map(destaqueDe);
  const achou = destaques.includes("achou");
  const apagado = destaques.length > 0 && destaques.every((d) => d === "apagado");
  const mostrarLinhas = aberta || achou || (algumaSel && !todasSel);

  return (
    <div
      ref={setNodeRef}
      data-card-id={parada.ids[0]}
      className={cn(
        "rounded-lg border bg-card text-sm shadow-sm",
        todasSel && "border-accent ring-2 ring-accent bg-accent/5",
        achou && "ring-2 ring-amber-400",
        apagado && "opacity-35",
        isDragging && "opacity-50",
      )}
    >
      <div className="flex items-start gap-1.5 p-2.5">
        <div className="flex shrink-0 flex-col items-center gap-1">
          <button
            type="button"
            title="Arrastar o cliente inteiro"
            className="mt-0.5 cursor-grab touch-none text-muted-foreground hover:text-foreground active:cursor-grabbing"
            {...listeners}
            {...attributes}
          >
            <GripVertical className="h-4 w-4" />
          </button>
          <input
            type="checkbox"
            aria-label="Selecionar o cliente inteiro"
            className="h-3.5 w-3.5 cursor-pointer"
            checked={todasSel}
            ref={(el) => {
              if (el) el.indeterminate = algumaSel && !todasSel;
            }}
            onChange={() => alternarSelecao(parada.ids)}
          />
        </div>
        <button
          type="button"
          className="min-w-0 flex-1 text-left"
          onClick={(e) => {
            if (e.ctrlKey || e.metaKey || e.shiftKey) {
              alternarSelecao(parada.ids);
              return;
            }
            setAberta((v) => !v);
          }}
        >
          <div className="flex items-center gap-1.5">
            <span
              className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full px-1 text-[11px] font-bold text-white"
              style={{ background: cor }}
              title={`${parada.numero}ª entrega`}
            >
              {parada.numero}
            </span>
            <div className="truncate font-semibold" title={parada.cliente}>
              {parada.apelido || parada.cliente}
            </div>
          </div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">{parada.local}</div>
          <LinhaAgenda a={agendaParada} />
          {semLocal && (
            <div className="mt-1 inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-amber-800">
              <MapPinOff className="h-3 w-3" /> Sem localização no mapa
            </div>
          )}
          {primeira.entrega_em && (
            <div className="mt-1 line-clamp-2 rounded bg-violet-500/10 px-1.5 py-0.5 text-[11px] font-medium text-violet-700">
              Entregar em: {primeira.entrega_em}
            </div>
          )}
          {primeira.obs_recebimento && (
            <div className="mt-1 flex items-start gap-1 text-[11px] text-sky-700">
              <Clock className="mt-0.5 h-3 w-3 shrink-0" />
              <span className="line-clamp-2">{primeira.obs_recebimento}</span>
            </div>
          )}
          <div className="mt-1.5 flex items-center justify-between">
            <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
              {mostrarLinhas ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              {parada.linhas.length} linhas
            </span>
            <span className="font-mono text-sm font-bold">{kg(parada.peso)}</span>
          </div>
        </button>
        {acoesParada && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="shrink-0 rounded p-1 hover:bg-muted"
                aria-label="Ações da parada"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <ItensAcoesParada acoes={acoesParada} />
              {destinos
                .filter((d) => d.id !== columnId)
                .map((d) => (
                  <DropdownMenuItem
                    key={d.id}
                    onClick={() => parada.linhas.forEach((l) => onMoveTo(d.id, l))}
                  >
                    Mover cliente para {d.label}
                  </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      {mostrarLinhas && (
        <div className="space-y-1 border-t bg-muted/20 p-1.5">
          {parada.linhas.map((l, i) => (
            <PedidoKanbanCard
              key={parada.ids[i]}
              pedido={l}
              columnId={columnId}
              destinos={destinos}
              compacto
              onMoveTo={(dest) => onMoveTo(dest, l)}
              onOpenAudit={onOpenAudit}
              onDivisao={divisaoDoCard(onDivisao, l)}
              {...propsCard(parada.ids[i])}
            />
          ))}
        </div>
      )}
    </div>
  );
}
