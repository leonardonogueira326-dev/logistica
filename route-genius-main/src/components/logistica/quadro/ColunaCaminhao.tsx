import { useDraggable, useDroppable } from "@dnd-kit/core";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  GripVertical,
  ListChecks,
  Lock,
  LockOpen,
  MapPinOff,
  MoreHorizontal,
  Truck,
  X,
} from "lucide-react";
import { useState } from "react";

import {
  ItensAcoesParada,
  LinhaAgenda,
  PedidoKanbanCard,
  type AcoesParada,
  type CardPedido,
} from "@/components/logistica/PedidoKanbanCard";
import { AcoesDivisao, PropsCardFn, divisaoDoCard } from "@/components/logistica/quadro/comum";
import { EquipeEditor } from "@/components/logistica/quadro/EquipeEditor";
import { VehicleMetrics } from "@/components/logistica/VehicleMetrics";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  type AgendaParada,
  type EquipeVeiculo,
  type PainelVeiculo,
  type Roteirizacao,
} from "@/lib/logistica-types";
import { kg } from "@/lib/mensagens";
import { checklist, paradas, type Parada } from "@/lib/montagem";
import { cn } from "@/lib/utils";

/** Coluna do caminhão: cabeçalho com resumo, checklist "pronto para sair" e as paradas na ordem de entrega. */
export function ColunaCaminhao({
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

/** Parada com várias linhas do mesmo cliente: um card só, que abre as linhas. Arrastar o cabeçalho leva todas. */
export function ParadaGrupo({
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
