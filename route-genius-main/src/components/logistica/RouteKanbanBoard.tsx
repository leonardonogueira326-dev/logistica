import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  Inbox,
  Loader2,
  MapPin,
  PackageSearch,
  PhoneCall,
  Truck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PedidoAuditSheet } from "@/components/logistica/PedidoAuditSheet";
import {
  PedidoKanbanCard,
  getCardId,
  type CardPedido,
} from "@/components/logistica/PedidoKanbanCard";
import { AbaAlocar } from "@/components/logistica/quadro/AbaAlocar";
import { ColunaCaminhao } from "@/components/logistica/quadro/ColunaCaminhao";
import {
  ABAS_ALOCAR,
  COLUNAS_NAO_VEICULO,
  MoverLoteFn,
  PendingMove,
  cardTravado,
  colisao,
  pendenciasDoCard,
  transportadoraADefinir,
} from "@/components/logistica/quadro/comum";
import { KanbanColumn, SegundaViagem } from "@/components/logistica/quadro/KanbanColumn";
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
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  COLUMN_BACKLOG,
  COLUMN_BACKLOG_FUTURO,
  COLUMN_BACKLOG_LOCAL,
  COLUMN_COLETAS,
  MOTIVOS_BACKLOG,
  SUFIXO_VIAGEM_RETORNO,
  idRetornoVeiculo,
  type EquipeVeiculo,
  type OperacaoDivisao,
  type PedidoConsolidado,
  type Roteirizacao,
} from "@/lib/logistica-types";
import { kg } from "@/lib/mensagens";
import { casaBusca, corDoCaminhao } from "@/lib/montagem";
import { cn } from "@/lib/utils";

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
    transportadora_codigo?: string;
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
    | (PendingMove & {
        titulo: string;
        representante: string;
        destinoLabel: string;
        aDefinir: number;
        dataFutura: number;
      })
    | null
  >(null);
  const [repQuem, setRepQuem] = useState("");
  const [repTransp, setRepTransp] = useState("");
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
          transportadora_codigo: move.transportadoraCodigo,
        });
      } else {
        await onMove({
          numero_pedido: move.ids[0],
          destino: move.destino,
          motivo: move.motivo,
          forcar: move.forcar,
          liberar_representante: move.liberarRepresentante,
          autorizado_por: move.autorizadoPor,
          transportadora_codigo: move.transportadoraCodigo,
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
        setRepTransp("");
        setRepErro("");
        const aDefinir = comRep.filter(transportadoraADefinir).length;
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
          aDefinir,
          dataFutura: comRep.length - aDefinir,
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
      await executeMove({
        ...repModal,
        liberarRepresentante: true,
        autorizadoPor: repQuem.trim(),
        transportadoraCodigo: repTransp.trim(),
      });
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
            <strong className="text-foreground">{repModal?.titulo}</strong>{" "}
            {repModal?.aDefinir && !repModal.dataFutura
              ? "está com a transportadora a definir."
              : repModal?.aDefinir
                ? "tem Dt. Produção futura ou transportadora a definir."
                : "tem Dt. Produção futura."}{" "}
            Só carregue em <strong className="text-foreground">{repModal?.destinoLabel}</strong> se
            o representante autorizou.
          </p>
          {!!repModal?.aDefinir && (
            <label className="block text-sm">
              <span className="text-xs font-medium text-muted-foreground">
                Transportadora que o representante definiu (código da base)
              </span>
              <input
                className="mt-1 w-full px-3 py-2 text-sm rounded-md border border-input bg-background font-mono"
                inputMode="numeric"
                value={repTransp}
                onChange={(e) => setRepTransp(e.target.value)}
                placeholder="ex.: 1073"
              />
              {!repTransp.trim() && (
                <span className="mt-1 block text-xs text-amber-700">
                  Sem o código a carga sobe sem o endereço de entrega.
                </span>
              )}
            </label>
          )}
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
