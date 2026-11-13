import { useDraggable, useDroppable } from "@dnd-kit/core";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Download,
  GripVertical,
  Loader2,
  Lock,
  LockOpen,
  Truck,
} from "lucide-react";
import { useState } from "react";

import { BotaoCopiar } from "@/components/BotaoCopiar";
import {
  PedidoKanbanCard,
  getCardId,
  type CardPedido,
} from "@/components/logistica/PedidoKanbanCard";
import {
  AcoesDivisao,
  PropsCardFn,
  TeoBadge,
  divisaoDoCard,
  formatTeoMin,
} from "@/components/logistica/quadro/comum";
import { EquipeEditor } from "@/components/logistica/quadro/EquipeEditor";
import { VehicleMetrics } from "@/components/logistica/VehicleMetrics";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { idRetornoVeiculo, type EquipeVeiculo, type Roteirizacao } from "@/lib/logistica-types";
import { kg, mensagemRepresentante } from "@/lib/mensagens";
import { cn } from "@/lib/utils";

export function KanbanColumn({
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

/** Representantes na ordem da coluna, cada um com as suas linhas. */
export function gruposRepresentante(items: CardPedido[]) {
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
export function GrupoRepresentante({
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

/** 2ª viagem (tarde) dentro do mesmo card do caminhão, separada por uma faixa. */
export function SegundaViagem({
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
