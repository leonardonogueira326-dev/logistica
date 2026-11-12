import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { Check, Keyboard, Loader2, ShieldAlert, Truck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { BotaoCopiar } from "@/components/BotaoCopiar";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { getStoredSessionId, useLogisticaSession } from "@/hooks/useLogisticaSession";
import type { FraseObservacao, PedidoConsolidado } from "@/lib/logistica-types";
import {
  COD_PROCESSANDO_IA,
  COD_REVISAO_OBRIGATORIA,
  EMPRESAS_INDUSTRIALIZACAO,
  OPCOES_SELETOR_FRETE,
  STATUS_FRETE_OPCOES,
  empresaDoSeletor,
  empresaRemessa,
  valorSeletorFrete,
  montarChaveMemoriaOperacional,
  montarChaveRegraAprendizado,
  palavraChaveParaAprendizado,
  rotuloSugestaoLlm,
} from "@/lib/logistica-types";
import { dataBR, kg, mensagemComercial, textoPendenteDesde } from "@/lib/mensagens";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/pendencias")({
  head: () => ({ meta: [{ title: "Conferência" }] }),
  component: PendenciasPage,
});

type Filtro = "todas" | "faltam" | "alerta" | "retira" | "frases";

const ehRetiraOuColeta = (c: PedidoConsolidado) => c.status === "RETIRA FOB" || c.status === "TERCEIRO";

const idLinha = (c: PedidoConsolidado) => c.id_item || c.numero_pedido_norm || c.numero_pedido;
const temPend = (c: PedidoConsolidado, p: string) => (c.pendencias ?? []).includes(p as never);
const cidadeDe = (c: PedidoConsolidado) => c.cidade_destino || c.cidade;

/** Por que esta linha precisa de um olhar na leitura do PDF (vazio = leitura ok). */
function motivoLeitura(c: PedidoConsolidado): string {
  if (c.status_ia === COD_PROCESSANDO_IA) return "IA analisando a observação…";
  if (c.revisao_obrigatoria === COD_REVISAO_OBRIGATORIA) {
    // Pagamento antecipado e peso zerado têm aba própria: não repetem aqui.
    const partes = (c.motivo_quarentena || "Revisão obrigatória")
      .split("|")
      .map((x) => x.trim())
      .filter(Boolean)
      .filter((x) => !/pagamento antecipado|peso zerado/i.test(x))
      // remessa / entregar em outra empresa já têm alerta próprio
      .filter((x) => !((c.industrializacao || c.entrega_em) && /palavra suspeita: (remessa|fort|lap)/i.test(x)));
    if (partes.length) return partes.join(" | ");
  }
  if (c.flag_revisao_llm === "SIM" && c.sugestao_llm_status)
    return `IA sugere: ${rotuloSugestaoLlm(c.sugestao_llm_status)}`;
  if (c.status === "BLOQUEIO FISCAL" || c.status === "TRAVADO COMERCIAL")
    return `${c.status}${c.motivo_bloqueio ? ` — ${c.motivo_bloqueio}` : ""}`;
  // Endereço só importa quando a logística entrega (retira / transportadora que coleta não)
  const logisticaEntrega = c.status === "LIBERADO" || c.status === "ENTREGA_TERCEIRO_HUB";
  if (logisticaEntrega && c.enriquecido_mestre !== "SIM" && c.enriquecido_mestre !== "HUB")
    return "Cliente não encontrado na base — confira cidade e CEP";
  return "";
}

type Alerta = {
  texto: string;
  tom: "erro" | "aviso" | "info" | "ok";
  acao?: "peso" | "comercial" | "frase";
  frase?: FraseObservacao;
};

/** "06/11/26" (ou 06/11, 06.11.2026) -> Date, usando o ano da lista quando faltar. */
function dataDaFrase(texto: string, refIso?: string): Date | null {
  const m = texto.match(/(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?/);
  if (!m) return null;
  const anoRef = refIso ? Number(refIso.slice(0, 4)) : new Date().getFullYear();
  let ano = m[3] ? Number(m[3]) : anoRef;
  if (ano < 100) ano += 2000;
  return new Date(ano, Number(m[2]) - 1, Number(m[1]));
}

function alertasDasFrases(c: PedidoConsolidado): Alerta[] {
  const out: Alerta[] = [];
  const ref = c.data_referencia ? new Date(`${c.data_referencia}T00:00:00`) : null;
  for (const f of c.frases ?? []) {
    if (f.situacao === "NOVA") {
      out.push({ texto: `Frase nova: “${f.texto}”`, tom: "aviso", acao: "frase", frase: f });
      continue;
    }
    if (f.situacao !== "OPERADOR") continue;
    const d = f.datas[0] ? dataDaFrase(f.datas[0], c.data_referencia) : null;
    const dTxt = f.datas[0] ?? "";
    if (f.significado === "FRETE")
      out.push({ texto: `Frete pela frase que você ensinou (${ROTULO_FRETE[f.status ?? ""] ?? f.status})`, tom: "ok" });
    else if (f.significado === "FATURAR_APOS")
      out.push(
        d && ref && d > ref
          ? { texto: `Só faturar a partir de ${dTxt} — ainda não pode sair`, tom: "erro" }
          : { texto: `Faturar a partir de ${dTxt} — já pode`, tom: "ok" },
      );
    else if (f.significado === "ENTREGAR_ATE")
      out.push(
        d && ref && d < ref
          ? { texto: `Prazo vencido: entregar até ${dTxt}`, tom: "erro" }
          : { texto: `Entregar até ${dTxt}`, tom: "aviso" },
      );
    else if (f.significado === "AVISAR") out.push({ texto: `📌 ${f.texto}`, tom: "aviso" });
  }
  return out;
}

/** Tudo o que o operador precisa ver numa linha, em uma lista só. */
function alertasDa(c: PedidoConsolidado): Alerta[] {
  const out: Alerta[] = [];
  const leitura = motivoLeitura(c);
  if (leitura) out.push({ texto: leitura, tom: c.status_ia === COD_PROCESSANDO_IA ? "info" : "erro" });
  if (ehRetiraOuColeta(c)) {
    if (c.evidencia_frete)
      out.push({ texto: c.evidencia_frete, tom: c.evidencia_nivel === "VERMELHO" ? "erro" : "ok" });
    if (c.liberacao_comercial === "AGUARDANDO") out.push({ texto: "Antecipado — o comercial trata", tom: "info" });
    if (!(c.peso_kg > 0)) out.push({ texto: "Peso zerado — não é da logística", tom: "info" });
  }
  if (temPend(c, "PESO_ZERADO")) out.push({ texto: "Peso zerado: informe o peso da expedição", tom: "erro", acao: "peso" });
  if (temPend(c, "PAGAMENTO_ANTECIPADO"))
    out.push({ texto: "Pagamento antecipado: aguardando o comercial", tom: "aviso", acao: "comercial" });
  if (c.liberacao_comercial === "LIBERADO" && !ehRetiraOuColeta(c))
    out.push({ texto: `Comercial liberou${c.liberacao_comercial_por ? ` (${c.liberacao_comercial_por})` : ""}`, tom: "ok" });
  if (temPend(c, "CONSULTA_REPRESENTANTE"))
    out.push({
      texto: `Consultar representante (${c.dias_uteis_antecedencia} d.u.) — fica no Kanban até liberar`,
      tom: "aviso",
    });
  out.push(...alertasDasFrases(c));
  if (c.industrializacao) out.push({ texto: c.industrializacao, tom: "info" });
  if (c.entrega_em) out.push({ texto: `Entregar em: ${c.entrega_em}`, tom: "info" });
  return out;
}

const temAlerta = (c: PedidoConsolidado) => alertasDa(c).some((a) => a.tom === "erro" || a.tom === "aviso");

const ROTULO_FRETE: Record<string, string> = {
  LIBERADO: "Frota própria",
  ENTREGA_TERCEIRO_HUB: "Levar na transp.",
  TERCEIRO: "Transp. coleta",
  "RETIRA FOB": "Cliente retira",
};

function PendenciasPage() {
  const navigate = useNavigate();
  const sessionId = getStoredSessionId();
  const {
    consolidadosQuery,
    confirmMutation,
    patchConsolidadoDebounced,
    comercialMutation,
    pesoMutation,
    conferirFreteMutation,
    ensinarFraseMutation,
  } = useLogisticaSession(sessionId);
  const [ensinando, setEnsinando] = useState<FraseObservacao | null>(null);

  const [filtro, setFiltro] = useState<Filtro>("todas");
  const [drafts, setDrafts] = useState<Record<string, PedidoConsolidado>>({});
  const [salvarRegras, setSalvarRegras] = useState<Record<string, boolean>>({});
  const [aberta, setAberta] = useState<string | null>(null);
  const [pesos, setPesos] = useState<Record<string, string>>({});
  const [aviso, setAviso] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  const [foco, setFoco] = useState(0);
  const linhasRef = useRef<Record<string, HTMLTableRowElement | null>>({});

  const data = consolidadosQuery.data;
  const validado = !!data?.validated;
  const linha = (c: PedidoConsolidado) => drafts[idLinha(c)] ?? c;

  // Ordem da lista do PDF: solicitação, depois Seq.
  const todas = useMemo(
    () =>
      [...(data?.consolidados ?? [])]
        .map((c, i) => ({ c, i }))
        .sort(
          (a, b) =>
            String(a.c.numero_solicitacao ?? "").localeCompare(String(b.c.numero_solicitacao ?? "")) ||
            Number(a.c.seq_solicitacao || 9999) - Number(b.c.seq_solicitacao || 9999) ||
            a.i - b.i,
        )
        .map((x) => x.c),
    [data],
  );
  const conferidas = todas.filter((c) => c.conferida === "SIM").length;
  const faltam = todas.length - conferidas;
  const visiveis = todas.filter((c) =>
    filtro === "faltam"
      ? c.conferida !== "SIM"
      : filtro === "alerta"
        ? temAlerta(c)
        : filtro === "retira"
          ? ehRetiraOuColeta(c)
          : filtro === "frases"
            ? (c.frases ?? []).some((f) => f.situacao === "NOVA")
            : true,
  );
  const frasesNovas = new Set(
    todas.flatMap((c) => (c.frases ?? []).filter((f) => f.situacao === "NOVA").map((f) => f.chave)),
  ).size;
  const semAlertaAConferir = todas.filter((c) => c.conferida !== "SIM" && !temAlerta(c));
  const antecipados = todas.filter((c) => temPend(c, "PAGAMENTO_ANTECIPADO"));
  const linhaAberta = aberta ? todas.find((c) => idLinha(c) === aberta) ?? null : null;
  const ocupado = comercialMutation.isPending || pesoMutation.isPending || conferirFreteMutation.isPending;

  const patch = (c: PedidoConsolidado, campos: Partial<PedidoConsolidado>) => {
    if (!sessionId) return;
    const id = idLinha(c);
    setDrafts((prev) => ({ ...prev, [id]: { ...(prev[id] ?? c), ...campos } }));
    patchConsolidadoDebounced(sessionId, id, campos);
  };

  /** Caixa de frete: frete comum ou "levar para industrializar" (o servidor troca o destino). */
  const mudarFrete = (c: PedidoConsolidado, valor: string) => {
    if (!sessionId) return;
    const id = idLinha(c);
    const empresa = empresaDoSeletor(valor);
    const eraRemessa = !!empresaRemessa(linha(c));
    if (!empresa && !eraRemessa) {
      patch(c, { status: valor });
      return;
    }
    // Destino muda no servidor: mostra o que ele devolver (sem rascunho local)
    setDrafts((prev) => {
      const { [id]: _, ...resto } = prev;
      return resto;
    });
    patchConsolidadoDebounced(
      sessionId,
      id,
      empresa ? { remessa_industrializacao: empresa } : { remessa_industrializacao: "", status: valor },
    );
  };

  const conferir = async (ids: string[], conferido = true) => {
    if (!sessionId || !ids.length) return;
    const r = await conferirFreteMutation.mutateAsync({ sid: sessionId, body: { ids, conferido } });
    setAviso(r.message);
  };

  const comercialLiberou = async (c: PedidoConsolidado) => {
    if (!sessionId) return;
    const quem = window.prompt("Quem do comercial liberou (e-mail)?");
    if (!quem?.trim()) return;
    const r = await comercialMutation.mutateAsync({
      sid: sessionId,
      body: { ids: [idLinha(c)], resultado: "LIBERADO", liberado_por: quem.trim(), obs: "" },
    });
    setAviso(r.message);
  };

  const salvarPeso = async (c: PedidoConsolidado) => {
    const valor = Number(String(pesos[idLinha(c)] ?? "").replace(",", "."));
    if (!sessionId || !(valor > 0)) return;
    const r = await pesoMutation.mutateAsync({ sid: sessionId, body: { id: idLinha(c), peso_kg: valor } });
    setAviso(r.message);
  };

  const montarCargas = async () => {
    if (!sessionId || !data) return;
    if (validado) {
      navigate({ to: "/roteirizar" });
      return;
    }
    setConfirmando(true);
    try {
      const regrasNovas: Record<string, string> = {};
      const memoriaNovas: Record<string, string> = {};
      for (const row of data.consolidados) {
        const id = idLinha(row);
        if (!salvarRegras[id]) continue;
        const draft = drafts[id] ?? row;
        const chave = montarChaveRegraAprendizado(row.cliente_codigo, palavraChaveParaAprendizado(row));
        if (chave && draft.status) regrasNovas[chave] = draft.status;
        const chaveMemoria = montarChaveMemoriaOperacional(row.observacao_comercial);
        if (chaveMemoria && draft.status) memoriaNovas[chaveMemoria] = draft.status;
      }
      await confirmMutation.mutateAsync({ sid: sessionId, regrasNovas, memoriaNovas });
      navigate({ to: "/roteirizar" });
    } catch (e) {
      setAviso(e instanceof Error ? e.message : "Não foi possível montar as cargas.");
    } finally {
      setConfirmando(false);
    }
  };

  // Teclado: ↑/↓ navega, Enter confere e desce, Espaço abre os detalhes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement;
      if (aberta || ensinando || alvo.closest("input, textarea, select, [role='combobox'], [role='listbox'], button")) return;
      const atual = visiveis[foco];
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setFoco((f) => Math.min(f + 1, visiveis.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setFoco((f) => Math.max(f - 1, 0));
      } else if (e.key === "Enter" && atual) {
        e.preventDefault();
        void conferir([idLinha(atual)], atual.conferida !== "SIM");
        setFoco((f) => Math.min(f + 1, visiveis.length - 1));
      } else if (e.key === " " && atual) {
        e.preventDefault();
        setAberta(idLinha(atual));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    const c = visiveis[foco];
    if (c) linhasRef.current[idLinha(c)]?.scrollIntoView({ block: "nearest" });
  }, [foco, visiveis]);

  if (!sessionId) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Nenhuma sessão ativa. Faça o upload em{" "}
        <Link to="/upload" className="font-semibold underline">
          Upload
        </Link>
        .
      </div>
    );
  }

  const pct = todas.length ? Math.round((conferidas / todas.length) * 100) : 0;
  const chip = (id: Filtro, rotulo: string, n?: number) => (
    <button
      type="button"
      onClick={() => {
        setFiltro(id);
        setFoco(0);
      }}
      className={cn(
        "rounded-full border px-3 py-1 text-sm",
        filtro === id ? "border-accent bg-accent text-accent-foreground" : "bg-background hover:bg-muted",
      )}
    >
      {rotulo}
      {n !== undefined && <span className="ml-1.5 opacity-80">{n}</span>}
    </button>
  );

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Conferência</h1>
          <p className="text-sm text-muted-foreground">
            Confira linha a linha, na ordem da lista
            {todas[0]?.data_referencia ? ` de ${dataBR(todas[0].data_referencia)}` : ""}. Só linha conferida vai para o
            Kanban.
          </p>
        </div>
        <button
          disabled={!data || confirmando || (!validado && faltam > 0)}
          onClick={() => void montarCargas()}
          title={!validado && faltam ? `Faltam ${faltam} linha(s) para conferir` : undefined}
          className={cn(
            "inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold shadow-sm",
            !data || confirmando || (!validado && faltam > 0)
              ? "bg-muted text-muted-foreground cursor-not-allowed"
              : "bg-accent text-accent-foreground hover:opacity-90",
          )}
        >
          {confirmando ? <Loader2 className="w-4 h-4 animate-spin" /> : <Truck className="w-4 h-4" />}
          {validado ? "Ir para o Kanban" : faltam > 0 ? `Montar cargas (faltam ${faltam})` : "Montar cargas"}
        </button>
      </div>

      <div className="rounded-xl border bg-card p-3 space-y-3">
        <div className="flex items-center gap-3">
          <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
          </div>
          <span className="text-sm font-semibold tabular-nums">
            {conferidas} de {todas.length} conferidas
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {chip("todas", "Todas", todas.length)}
          {chip("faltam", "Faltam conferir", faltam)}
          {chip("alerta", "Com alerta", todas.filter(temAlerta).length)}
          {chip("retira", "Retira / coleta", todas.filter(ehRetiraOuColeta).length)}
          {chip("frases", "Frases novas", frasesNovas)}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {antecipados.length > 0 && (
              <BotaoCopiar rotulo={`E-mail p/ comercial (${antecipados.length})`} texto={mensagemComercial(antecipados)} />
            )}
            <button
              type="button"
              disabled={ocupado || !semAlertaAConferir.length}
              onClick={() => void conferir(semAlertaAConferir.map(idLinha))}
              className="rounded-md border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
              title="Confere de uma vez as linhas que não têm nenhum alerta"
            >
              Conferir as sem alerta ({semAlertaAConferir.length})
            </button>
          </div>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Keyboard className="w-3.5 h-3.5" /> ↑ ↓ navega · <b>Enter</b> confere e desce · <b>Espaço</b> abre os detalhes
        </div>
      </div>

      {consolidadosQuery.isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Carregando…
        </div>
      )}
      {consolidadosQuery.error && (
        <div className="rounded-xl border border-destructive/40 bg-destructive/10 p-4 text-sm flex gap-2">
          <ShieldAlert className="w-5 h-5 shrink-0" />
          {consolidadosQuery.error.message}
        </div>
      )}
      {aviso && (
        <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm">{aviso}</div>
      )}

      <div className="overflow-x-auto rounded-xl border bg-card shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-muted/40 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
              <th className="py-2.5 pl-4 pr-2 w-10">Seq</th>
              <th className="py-2.5 pr-3">Pedido · OF</th>
              <th className="py-2.5 pr-3">Cliente</th>
              <th className="py-2.5 pr-3">Cidade</th>
              <th className="py-2.5 pr-3 text-right">Peso</th>
              <th className="py-2.5 pr-3">Frete</th>
              <th className="py-2.5 pr-3">Alertas / ação</th>
              <th className="py-2.5 pr-4 w-28 text-right">Conferido</th>
            </tr>
          </thead>
          <tbody>
            {visiveis.map((c, i) => {
              const d = linha(c);
              const ok = c.conferida === "SIM";
              const alertas = alertasDa(c);
              const id = idLinha(c);
              return (
                <tr
                  key={id}
                  ref={(el) => {
                    linhasRef.current[id] = el;
                  }}
                  onClick={() => setFoco(i)}
                  onDoubleClick={() => setAberta(id)}
                  className={cn(
                    "border-t align-top",
                    ok && "bg-emerald-500/[0.05] text-muted-foreground",
                    !ok && alertas.some((a) => a.tom === "erro") && "bg-destructive/[0.04]",
                    i === foco && "outline outline-2 -outline-offset-2 outline-accent",
                  )}
                >
                  <td className="py-2 pl-4 pr-2 font-mono text-xs text-muted-foreground">{c.seq_solicitacao}</td>
                  <td className="py-2 pr-3">
                    <PedidoOf c={c} />
                  </td>
                  <td className="py-2 pr-3">
                    <button type="button" className="text-left font-medium hover:underline" onClick={() => setAberta(id)}>
                      {d.cliente}
                    </button>
                    {ehRetiraOuColeta(c) && c.transportadora && (
                      <span className="block text-[11px] text-muted-foreground">{c.transportadora.split(" - ")[0]}</span>
                    )}
                  </td>
                  <td className="py-2 pr-3">{cidadeDe(d)}</td>
                  <td className="py-2 pr-3 text-right whitespace-nowrap font-mono">{kg(c.peso_kg)}</td>
                  <td className="py-2 pr-3">
                    {validado ? (
                      <span className="text-xs">
                        {empresaRemessa(d) ? `Industrialização (${empresaRemessa(d)})` : ROTULO_FRETE[d.status] ?? d.status}
                      </span>
                    ) : (
                      <SeletorFrete valor={valorSeletorFrete(d)} readonly={false} onChange={(v) => mudarFrete(c, v)} />
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    <div className="flex flex-col gap-1">
                      {alertas.map((a, k) => (
                        <span
                          key={k}
                          className={cn(
                            "flex items-start gap-1.5 text-xs",
                            a.tom === "erro" && "text-destructive",
                            a.tom === "aviso" && "text-amber-700",
                            a.tom === "info" && "text-muted-foreground",
                            a.tom === "ok" && "text-emerald-700",
                          )}
                        >
                          <span
                            className={cn(
                              "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                              a.tom === "erro" && "bg-destructive",
                              a.tom === "aviso" && "bg-amber-500",
                              a.tom === "info" && "bg-muted-foreground/50",
                              a.tom === "ok" && "bg-emerald-500",
                            )}
                          />
                          <span className="flex flex-wrap items-center gap-1.5">
                          {a.texto}
                          {a.acao === "peso" && (
                            <span className="inline-flex items-center gap-1">
                              <input
                                inputMode="decimal"
                                placeholder="kg"
                                className="w-20 rounded border border-input bg-background px-1.5 py-0.5 font-mono text-xs text-foreground"
                                value={pesos[id] ?? ""}
                                onChange={(e) => setPesos((p) => ({ ...p, [id]: e.target.value }))}
                                onKeyDown={(e) => e.key === "Enter" && void salvarPeso(c)}
                              />
                              <button
                                type="button"
                                disabled={ocupado}
                                className="rounded bg-accent px-2 py-0.5 text-[11px] text-accent-foreground"
                                onClick={() => void salvarPeso(c)}
                              >
                                Salvar
                              </button>
                            </span>
                          )}
                          {a.acao === "frase" && a.frase && (
                            <button
                              type="button"
                              className="rounded border border-amber-600/50 px-2 py-0.5 text-[11px] text-amber-800 hover:bg-amber-50"
                              onClick={(e) => {
                                e.stopPropagation();
                                setEnsinando(a.frase!);
                              }}
                            >
                              Ensinar
                            </button>
                          )}
                          {a.acao === "comercial" && (
                            <button
                              type="button"
                              disabled={ocupado}
                              className="rounded border border-emerald-600/50 px-2 py-0.5 text-[11px] text-emerald-700 hover:bg-emerald-50"
                              onClick={() => void comercialLiberou(c)}
                            >
                              Comercial liberou
                            </button>
                          )}
                          </span>
                        </span>
                      ))}
                      {!alertas.length && <span className="text-xs text-muted-foreground">—</span>}
                    </div>
                  </td>
                  <td className="py-2 pr-4 text-right">
                    <button
                      type="button"
                      disabled={ocupado}
                      onClick={(e) => {
                        e.stopPropagation();
                        setFoco(i);
                        void conferir([id], !ok);
                      }}
                      className={cn(
                        "inline-flex h-8 w-8 items-center justify-center rounded-md border",
                        ok ? "border-emerald-600 bg-emerald-600 text-white" : "bg-background hover:bg-muted",
                      )}
                      title={ok ? `Conferida ${c.conferida_em ?? ""} — clique para desfazer` : "Conferir (Enter)"}
                    >
                      <Check className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              );
            })}
            {!visiveis.length && (
              <tr>
                <td colSpan={8} className="p-8 text-center text-sm text-muted-foreground">
                  {filtro === "faltam" ? "Tudo conferido. Pode montar as cargas." : "Nenhuma linha neste filtro."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <EnsinarFrase
        frase={ensinando}
        ocupado={ensinarFraseMutation.isPending}
        onClose={() => setEnsinando(null)}
        onSalvar={async (significado, status) => {
          if (!sessionId || !ensinando) return;
          const r = await ensinarFraseMutation.mutateAsync({
            sid: sessionId,
            body: { chave: ensinando.chave, exemplo: ensinando.texto, significado, status },
          });
          setAviso(r.message);
          setEnsinando(null);
        }}
      />

      <DetalheLinha
        c={linhaAberta}
        draft={linhaAberta ? linha(linhaAberta) : null}
        readonly={validado}
        salvarRegra={linhaAberta ? !!salvarRegras[idLinha(linhaAberta)] : false}
        onSalvarRegra={(v) => linhaAberta && setSalvarRegras((p) => ({ ...p, [idLinha(linhaAberta)]: v }))}
        onPatch={(campos) => linhaAberta && patch(linhaAberta, campos)}
        onFrete={(v) => linhaAberta && mudarFrete(linhaAberta, v)}
        onClose={() => setAberta(null)}
      />
    </div>
  );
}

function PedidoOf({ c }: { c: PedidoConsolidado }) {
  return (
    <span className="font-mono text-xs">
      {c.numero_pedido}
      {c.of_ano && <span className="block text-[10px] text-muted-foreground">OF {c.of_ano}</span>}
      {c.pendente_desde && (
        <span className="mt-0.5 block font-sans text-[10px] font-semibold text-rose-700">
          {textoPendenteDesde(c.pendente_desde)}
        </span>
      )}
    </span>
  );
}

function SeletorFrete({
  valor,
  readonly,
  onChange,
}: {
  valor: string;
  readonly: boolean;
  onChange: (v: string) => void;
}) {
  const conhecido = OPCOES_SELETOR_FRETE.some((o) => o.value === valor);
  if (readonly) return <span className="text-xs">{valor || "—"}</span>;
  return (
    <span onClick={(e) => e.stopPropagation()}>
      <Select value={valor || "LIBERADO"} onValueChange={onChange}>
        <SelectTrigger className="h-8 min-w-[170px] text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {OPCOES_SELETOR_FRETE.map((o) => (
            <SelectItem key={o.value} value={o.value} className="text-xs">
              {o.label}
            </SelectItem>
          ))}
          {!conhecido && valor && (
            <SelectItem value={valor} className="text-xs">
              {valor}
            </SelectItem>
          )}
        </SelectContent>
      </Select>
    </span>
  );
}

const CAMPOS_EDITAVEIS: { campo: "cliente" | "bairro" | "cidade" | "cep" | "representante"; rotulo: string }[] = [
  { campo: "cliente", rotulo: "Cliente" },
  { campo: "cidade", rotulo: "Cidade" },
  { campo: "bairro", rotulo: "Bairro" },
  { campo: "cep", rotulo: "CEP" },
  { campo: "representante", rotulo: "Representante" },
];

function DetalheLinha({
  c,
  draft,
  readonly,
  salvarRegra,
  onSalvarRegra,
  onPatch,
  onFrete,
  onClose,
}: {
  c: PedidoConsolidado | null;
  draft: PedidoConsolidado | null;
  readonly: boolean;
  salvarRegra: boolean;
  onSalvarRegra: (v: boolean) => void;
  onPatch: (campos: Partial<PedidoConsolidado>) => void;
  onFrete: (valor: string) => void;
  onClose: () => void;
}) {
  const info = (rotulo: string, valor?: string | number) => (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{rotulo}</div>
      <div className="text-sm">{valor === undefined || valor === "" ? "—" : valor}</div>
    </div>
  );
  return (
    <Sheet open={!!c} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {c && draft && (
          <>
            <SheetHeader>
              <SheetTitle>
                {draft.cliente}
                <span className="block font-mono text-xs font-normal text-muted-foreground">
                  Pedido {c.numero_pedido}
                  {c.of_ano ? ` · OF ${c.of_ano}` : ""}
                </span>
              </SheetTitle>
            </SheetHeader>
            <div className="mt-4 space-y-5">
              {motivoLeitura(c) && (
                <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  {motivoLeitura(c)}
                </div>
              )}
              {c.entrega_em && (
                <div className="rounded-md border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-800">
                  <b>Entregar em:</b> {c.entrega_em}
                </div>
              )}
              {(c.pendencias ?? []).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {(c.pendencias ?? []).map((p) => (
                    <Badge key={p} variant="outline" className="text-[11px]">
                      {{ CONSULTA_REPRESENTANTE: "Consultar representante", PAGAMENTO_ANTECIPADO: "Aguardando comercial", PESO_ZERADO: "Peso zerado" }[p] ?? p}
                    </Badge>
                  ))}
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                {info("Peso", kg(c.peso_kg))}
                {info("Dt. Produção", c.data_producao)}
                {info("Rota", draft.rota_logistica)}
                {info("Dias úteis até a produção", c.dias_uteis_antecedencia)}
              </div>

              <div className="space-y-1">
                <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Frete</div>
                <SeletorFrete valor={valorSeletorFrete(draft)} readonly={readonly} onChange={onFrete} />
                {!readonly && draft.status !== c.status && !empresaRemessa(draft) && (
                  <label className="mt-2 flex items-start gap-2 text-xs">
                    <Checkbox checked={salvarRegra} onCheckedChange={(v) => onSalvarRegra(v === true)} />
                    <span>
                      Aprender: da próxima vez, fazer igual para este cliente
                      <span className="block font-mono text-muted-foreground">
                        {c.cliente_codigo}+{palavraChaveParaAprendizado(c) || "obs"}
                      </span>
                    </span>
                  </label>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                {CAMPOS_EDITAVEIS.map(({ campo, rotulo }) => (
                  <label key={campo} className={cn("block", campo === "cliente" && "col-span-2")}>
                    <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{rotulo}</span>
                    {readonly ? (
                      <div className="text-sm">{String(draft[campo] ?? "") || "—"}</div>
                    ) : (
                      <input
                        className="mt-0.5 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                        value={String(draft[campo] ?? "")}
                        onChange={(e) => onPatch({ [campo]: e.target.value })}
                      />
                    )}
                  </label>
                ))}
              </div>

              <div>
                <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Observação do pedido</div>
                <div className="mt-1 whitespace-pre-wrap rounded-md bg-muted/40 px-3 py-2 text-sm">
                  {c.observacao_comercial || "—"}
                </div>
              </div>
              {c.obs_recebimento && info("Horário de recebimento", c.obs_recebimento)}
              {c.auditoria && (
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Histórico</div>
                  <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                    {c.auditoria.split(" | ").map((a, i) => (
                      <div key={i}>{a}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

const OPCOES_FRASE: { valor: string; rotulo: string; ajuda: string }[] = [
  { valor: "IGNORAR", rotulo: "Não importa para a logística", ajuda: "Financeiro, fiscal, boleto… não aparece mais." },
  { valor: "FRETE", rotulo: "Muda o frete", ajuda: "Toda linha com esta frase vai para o frete escolhido." },
  { valor: "FATURAR_APOS", rotulo: "Prazo: só faturar a partir da data", ajuda: "A data é lida da frase em cada pedido." },
  { valor: "ENTREGAR_ATE", rotulo: "Prazo: entregar até a data", ajuda: "Avisa e fica vermelho se o prazo passou." },
  { valor: "AVISAR", rotulo: "Sempre me avisar", ajuda: "Mostra a frase toda vez (embalagem, parcial, ligar para alguém…)." },
  {
    valor: "INDUSTRIALIZACAO",
    rotulo: "Remessa para industrialização",
    ajuda: "Peso zerado: a logística leva até a empresa escolhida. Com peso: já voltou, segue o frete da linha.",
  },
];
const PRECISA_ESCOLHA: Record<string, boolean> = { FRETE: true, INDUSTRIALIZACAO: true };

function EnsinarFrase({
  frase,
  ocupado,
  onClose,
  onSalvar,
}: {
  frase: FraseObservacao | null;
  ocupado: boolean;
  onClose: () => void;
  onSalvar: (significado: string, status: string) => Promise<void>;
}) {
  const [significado, setSignificado] = useState("");
  const [status, setStatus] = useState("");
  useEffect(() => {
    setSignificado(frase?.sugestao || "AVISAR");
    setStatus(frase?.sugestao_status || "");
  }, [frase]);
  return (
    <Sheet open={!!frase} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>O que esta frase significa?</SheetTitle>
        </SheetHeader>
        {frase && (
          <div className="mt-4 space-y-4">
            <div className="rounded-md bg-muted/50 px-3 py-2 text-sm">“{frase.texto}”</div>
            <p className="text-xs text-muted-foreground">
              Vale para sempre, inclusive com outras datas e números. A opção marcada é a sugestão do sistema — confira.
            </p>
            <div className="space-y-2">
              {OPCOES_FRASE.map((o) => (
                <label
                  key={o.valor}
                  className={cn(
                    "flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2",
                    significado === o.valor && "border-accent bg-accent/5",
                  )}
                >
                  <input
                    type="radio"
                    name="significado"
                    className="mt-1"
                    checked={significado === o.valor}
                    onChange={() => {
                      setSignificado(o.valor);
                      if (o.valor !== significado) setStatus(o.valor === frase.sugestao ? frase.sugestao_status || "" : "");
                    }}
                  />
                  <span>
                    <span className="block text-sm font-medium">
                      {o.rotulo}
                      {frase.sugestao === o.valor && (
                        <span className="ml-2 rounded bg-muted px-1.5 text-[10px] font-normal text-muted-foreground">
                          sugestão
                        </span>
                      )}
                    </span>
                    <span className="block text-xs text-muted-foreground">{o.ajuda}</span>
                  </span>
                </label>
              ))}
            </div>
            {significado === "FRETE" && (
              <label className="block text-sm">
                <span className="text-xs text-muted-foreground">Frete</span>
                <select
                  className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="">Escolha…</option>
                  {STATUS_FRETE_OPCOES.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {significado === "INDUSTRIALIZACAO" && (
              <label className="block text-sm">
                <span className="text-xs text-muted-foreground">Empresa que industrializa</span>
                <select
                  className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="">Escolha…</option>
                  {EMPRESAS_INDUSTRIALIZACAO.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" className="rounded-md border px-4 py-2 text-sm" onClick={onClose}>
                Cancelar
              </button>
              <button
                type="button"
                disabled={ocupado || !significado || (PRECISA_ESCOLHA[significado] && !status)}
                className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground disabled:opacity-50"
                onClick={() => void onSalvar(significado, status)}
              >
                {ocupado ? "Salvando…" : "Ensinar"}
              </button>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
