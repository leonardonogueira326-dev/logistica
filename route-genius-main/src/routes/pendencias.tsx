import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  AlertTriangle,
  Banknote,
  Brain,
  CheckCircle2,
  ClipboardCheck,
  Loader2,
  PhoneCall,
  Scale,
  ScanSearch,
  ShieldAlert,
} from "lucide-react";
import { useMemo, useState } from "react";

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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getStoredSessionId, useLogisticaSession } from "@/hooks/useLogisticaSession";
import type { PedidoConsolidado } from "@/lib/logistica-types";
import {
  COD_PROCESSANDO_IA,
  COD_REVISAO_OBRIGATORIA,
  STATUS_FRETE_OPCOES,
  montarChaveMemoriaOperacional,
  montarChaveRegraAprendizado,
  palavraChaveParaAprendizado,
  rotuloSugestaoLlm,
} from "@/lib/logistica-types";
import { dataBR, kg, mensagemComercial } from "@/lib/mensagens";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/pendencias")({
  head: () => ({ meta: [{ title: "Pendências" }] }),
  component: PendenciasPage,
});

type Aba = "leitura" | "comercial" | "expedicao";

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
      .filter((x) => !(temPend(c, "PAGAMENTO_ANTECIPADO") && /pagamento antecipado/i.test(x)))
      .filter((x) => !(temPend(c, "PESO_ZERADO") && /peso zerado/i.test(x)));
    if (partes.length) return partes.join(" | ");
  }
  if (c.flag_revisao_llm === "SIM" && c.sugestao_llm_status)
    return `IA sugere: ${rotuloSugestaoLlm(c.sugestao_llm_status)}`;
  if (c.status === "BLOQUEIO FISCAL" || c.status === "TRAVADO COMERCIAL")
    return `${c.status}${c.motivo_bloqueio ? ` — ${c.motivo_bloqueio}` : ""}`;
  if (c.enriquecido_mestre !== "SIM") return "Cliente não encontrado na base — confira cidade e CEP";
  return "";
}

function PendenciasPage() {
  const navigate = useNavigate();
  const sessionId = getStoredSessionId();
  const {
    consolidadosQuery,
    confirmMutation,
    patchConsolidadoDebounced,
    comercialMutation,
    pesoMutation,
  } = useLogisticaSession(sessionId);

  const [aba, setAba] = useState<Aba>("leitura");
  const [todasLinhas, setTodasLinhas] = useState(false);
  const [mostrarLiberados, setMostrarLiberados] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, PedidoConsolidado>>({});
  const [salvarRegras, setSalvarRegras] = useState<Record<string, boolean>>({});
  const [aberta, setAberta] = useState<string | null>(null);
  const [selecionados, setSelecionados] = useState<Record<string, boolean>>({});
  const [comercialPor, setComercialPor] = useState("");
  const [comercialObs, setComercialObs] = useState("");
  const [pesos, setPesos] = useState<Record<string, string>>({});
  const [aviso, setAviso] = useState("");
  const [confirmando, setConfirmando] = useState(false);

  const data = consolidadosQuery.data;
  const todas = data?.consolidados ?? [];
  const validado = !!data?.validated;
  const linha = (c: PedidoConsolidado) => drafts[idLinha(c)] ?? c;

  const leitura = useMemo(
    () => todas.filter((c) => todasLinhas || motivoLeitura(c)),
    [todas, todasLinhas],
  );
  const nLeitura = todas.filter((c) => motivoLeitura(c)).length;
  const comercial = todas.filter(
    (c) => temPend(c, "PAGAMENTO_ANTECIPADO") || (mostrarLiberados && c.liberacao_comercial === "LIBERADO"),
  );
  const comercialPend = todas.filter((c) => temPend(c, "PAGAMENTO_ANTECIPADO"));
  const expedicao = todas.filter((c) => temPend(c, "PESO_ZERADO"));
  const nRepresentante = todas.filter(
    (c) => temPend(c, "CONSULTA_REPRESENTANTE") && !temPend(c, "PAGAMENTO_ANTECIPADO") && !temPend(c, "PESO_ZERADO"),
  ).length;

  const linhaAberta = aberta ? todas.find((c) => idLinha(c) === aberta) ?? null : null;

  const patch = (c: PedidoConsolidado, campos: Partial<PedidoConsolidado>) => {
    if (!sessionId) return;
    const id = idLinha(c);
    setDrafts((prev) => ({ ...prev, [id]: { ...(prev[id] ?? c), ...campos } }));
    patchConsolidadoDebounced(sessionId, id, campos);
  };

  const confirmar = async () => {
    if (!sessionId || !data) return;
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
    } finally {
      setConfirmando(false);
    }
  };

  const marcados = (lista: PedidoConsolidado[]) => lista.map(idLinha).filter((id) => selecionados[id]);
  const alvoComercial = marcados(comercialPend).length ? marcados(comercialPend) : comercialPend.map(idLinha);

  const responderComercial = async (ids: string[], resultado: "LIBERADO" | "AGUARDANDO") => {
    if (!sessionId || !ids.length) return;
    const r = await comercialMutation.mutateAsync({
      sid: sessionId,
      body: { ids, resultado, liberado_por: comercialPor, obs: comercialObs },
    });
    setAviso(r.message);
    setSelecionados({});
  };

  const salvarPeso = async (c: PedidoConsolidado) => {
    const valor = Number(String(pesos[idLinha(c)] ?? "").replace(",", "."));
    if (!sessionId || !(valor > 0)) return;
    const r = await pesoMutation.mutateAsync({ sid: sessionId, body: { id: idLinha(c), peso_kg: valor } });
    setAviso(r.message);
  };

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

  const ocupado = comercialMutation.isPending || pesoMutation.isPending;

  return (
    <div className="p-6 space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Pendências</h1>
          <p className="text-sm text-muted-foreground max-w-3xl">
            Só o que ainda não pode ir para o caminhão
            {todas[0]?.data_referencia ? ` — solicitação de ${dataBR(todas[0].data_referencia)}` : ""}. Clique numa
            linha para ver todos os detalhes.
          </p>
        </div>
        <button
          disabled={!data || validado || confirmando}
          onClick={() => void confirmar()}
          className={cn(
            "inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold shadow-sm",
            validado || confirmando
              ? "bg-muted text-muted-foreground cursor-not-allowed"
              : "bg-accent text-accent-foreground hover:opacity-90",
          )}
          title="Fecha a conferência da leitura e libera a montagem das cargas"
        >
          {confirmando ? <Loader2 className="w-4 h-4 animate-spin" /> : <ClipboardCheck className="w-4 h-4" />}
          {validado ? "Leitura conferida" : "Confirmar leitura e montar cargas"}
        </button>
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
        <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2.5 text-sm">{aviso}</div>
      )}

      {nRepresentante > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/30 px-4 py-2.5 text-sm">
          <PhoneCall className="w-4 h-4 text-muted-foreground" />
          {nRepresentante} {nRepresentante === 1 ? "linha aguarda" : "linhas aguardam"} o representante — ficam no
          Kanban, coluna “Consultar representante”.
          <Link to="/roteirizar" className="font-semibold text-accent underline">
            Abrir Roteirizar
          </Link>
        </div>
      )}

      <Tabs value={aba} onValueChange={(v) => setAba(v as Aba)}>
        <TabsList>
          <TabsTrigger value="leitura" className="gap-1.5">
            <ScanSearch className="w-4 h-4" /> Conferir leitura <Contador n={validado ? 0 : nLeitura} />
          </TabsTrigger>
          <TabsTrigger value="comercial" className="gap-1.5">
            <Banknote className="w-4 h-4" /> Comercial <Contador n={comercialPend.length} />
          </TabsTrigger>
          <TabsTrigger value="expedicao" className="gap-1.5">
            <Scale className="w-4 h-4" /> Expedição <Contador n={expedicao.length} />
          </TabsTrigger>
        </TabsList>

        <TabsContent value="leitura" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              {validado && <b className="text-foreground">Leitura já conferida — só consulta. </b>}
              Linhas em que o sistema ficou em dúvida ao ler o PDF. Corrija o frete ou o cadastro — se marcar
              “aprender”, ele faz sozinho da próxima vez.
            </p>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={todasLinhas} onCheckedChange={(v) => setTodasLinhas(v === true)} />
              Mostrar todas as linhas ({todas.length})
            </label>
          </div>
          <Tabela
            vazio="Nenhuma dúvida de leitura. Pode confirmar e montar as cargas."
            colunas={["Pedido · OF", "Cliente", "Cidade", "Peso", "Motivo", "Frete"]}
            linhas={leitura.map((c) => {
              const d = linha(c);
              const motivo = motivoLeitura(c);
              return {
                id: idLinha(c),
                destaque: c.revisao_obrigatoria === COD_REVISAO_OBRIGATORIA,
                celulas: [
                  <PedidoOf key="p" c={c} />,
                  <span key="c" className="font-medium">{d.cliente}</span>,
                  cidadeDe(d),
                  <span key="k" className="whitespace-nowrap font-mono">{kg(c.peso_kg)}</span>,
                  motivo ? (
                    <span key="m" className="flex items-start gap-1 text-xs text-destructive">
                      {c.status_ia === COD_PROCESSANDO_IA ? (
                        <Loader2 className="w-3.5 h-3.5 shrink-0 mt-0.5 animate-spin" />
                      ) : c.flag_revisao_llm === "SIM" ? (
                        <Brain className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                      ) : (
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                      )}
                      <span className="line-clamp-2">{motivo}</span>
                    </span>
                  ) : (
                    <span key="m" className="text-xs text-muted-foreground">—</span>
                  ),
                  <SeletorFrete key="f" valor={d.status} readonly={validado} onChange={(status) => patch(c, { status })} />,
                ],
              };
            })}
            onAbrir={setAberta}
          />
        </TabsContent>

        <TabsContent value="comercial" className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3 py-2">
            <BotaoCopiar
              rotulo="Copiar e-mail p/ comercial"
              disabled={!comercialPend.length}
              texto={mensagemComercial(
                comercialPend.filter((c) => !marcados(comercialPend).length || selecionados[idLinha(c)]),
              )}
            />
            <input
              className="w-40 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
              placeholder="Liberado por *"
              value={comercialPor}
              onChange={(e) => setComercialPor(e.target.value)}
            />
            <input
              className="w-56 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
              placeholder="E-mail (assunto / data)"
              value={comercialObs}
              onChange={(e) => setComercialObs(e.target.value)}
            />
            <button
              type="button"
              disabled={ocupado || !alvoComercial.length || !comercialPor.trim()}
              title={!comercialPor.trim() ? "Informe quem do comercial liberou" : undefined}
              className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-50"
              onClick={() => void responderComercial(alvoComercial, "LIBERADO")}
            >
              Comercial liberou{" "}
              {marcados(comercialPend).length ? `(${marcados(comercialPend).length})` : "todos"}
            </button>
            <label className="ml-auto flex items-center gap-2 text-sm">
              <Checkbox checked={mostrarLiberados} onCheckedChange={(v) => setMostrarLiberados(v === true)} />
              Mostrar já liberados
            </label>
          </div>
          <Tabela
            vazio="Nenhum pagamento antecipado aguardando."
            colunas={["", "Pedido · OF", "Cliente", "Cidade", "Peso", "Situação"]}
            linhas={comercial.map((c) => ({
              id: idLinha(c),
              apagada: c.liberacao_comercial === "LIBERADO",
              celulas: [
                <span key="s" onClick={(e) => e.stopPropagation()}>
                  <Checkbox
                    disabled={c.liberacao_comercial === "LIBERADO"}
                    checked={!!selecionados[idLinha(c)]}
                    onCheckedChange={(v) => setSelecionados((p) => ({ ...p, [idLinha(c)]: v === true }))}
                  />
                </span>,
                <PedidoOf key="p" c={c} />,
                <span key="c" className="font-medium">
                  {c.cliente}
                  <span className="block text-[11px] font-normal text-muted-foreground">{c.representante}</span>
                </span>,
                cidadeDe(c),
                <span key="k" className="whitespace-nowrap font-mono">{kg(c.peso_kg)}</span>,
                c.liberacao_comercial === "LIBERADO" ? (
                  <span key="x" className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <Badge className="bg-emerald-500/15 text-emerald-700 border border-emerald-500/40 hover:bg-emerald-500/15 gap-1">
                      <CheckCircle2 className="w-3 h-3" /> {c.liberacao_comercial_por || "Liberado"}
                    </Badge>
                    <button
                      type="button"
                      className="text-[11px] text-muted-foreground underline"
                      onClick={() => void responderComercial([idLinha(c)], "AGUARDANDO")}
                    >
                      desfazer
                    </button>
                  </span>
                ) : (
                  <span key="x" className="text-xs text-amber-700">Aguardando e-mail do comercial</span>
                ),
              ],
            }))}
            onAbrir={setAberta}
          />
        </TabsContent>

        <TabsContent value="expedicao" className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Peso zerado no PDF: informe o peso passado pela expedição (chat do Teams). O destino está na observação.
          </p>
          <Tabela
            vazio="Nenhuma linha com peso zerado."
            colunas={["Pedido · OF", "Cliente", "Cidade", "Destino (observação)", "Peso (kg)"]}
            linhas={expedicao.map((c) => ({
              id: idLinha(c),
              celulas: [
                <PedidoOf key="p" c={c} />,
                <span key="c" className="font-medium">{c.cliente}</span>,
                cidadeDe(c),
                <span key="o" className="line-clamp-2 text-xs text-muted-foreground" title={c.observacao_comercial}>
                  {c.observacao_comercial || "—"}
                </span>,
                <span key="k" className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                  <input
                    inputMode="decimal"
                    placeholder="kg"
                    className="w-24 rounded-md border border-input bg-background px-2 py-1 font-mono text-sm"
                    value={pesos[idLinha(c)] ?? ""}
                    onChange={(e) => setPesos((p) => ({ ...p, [idLinha(c)]: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && void salvarPeso(c)}
                  />
                  <button
                    type="button"
                    disabled={ocupado || !(Number(String(pesos[idLinha(c)] ?? "").replace(",", ".")) > 0)}
                    className="rounded-md bg-accent px-3 py-1 text-sm text-accent-foreground disabled:opacity-50"
                    onClick={() => void salvarPeso(c)}
                  >
                    Salvar
                  </button>
                </span>,
              ],
            }))}
            onAbrir={setAberta}
          />
        </TabsContent>
      </Tabs>

      <DetalheLinha
        c={linhaAberta}
        draft={linhaAberta ? linha(linhaAberta) : null}
        readonly={validado}
        salvarRegra={linhaAberta ? !!salvarRegras[idLinha(linhaAberta)] : false}
        onSalvarRegra={(v) => linhaAberta && setSalvarRegras((p) => ({ ...p, [idLinha(linhaAberta)]: v }))}
        onPatch={(campos) => linhaAberta && patch(linhaAberta, campos)}
        onClose={() => setAberta(null)}
      />
    </div>
  );
}

function Contador({ n }: { n: number }) {
  return (
    <span
      className={cn(
        "ml-1 rounded-full px-1.5 text-[11px] font-semibold",
        n ? "bg-destructive/15 text-destructive" : "bg-muted text-muted-foreground",
      )}
    >
      {n}
    </span>
  );
}

function PedidoOf({ c }: { c: PedidoConsolidado }) {
  return (
    <span className="font-mono text-xs">
      {c.numero_pedido}
      {c.of_ano && <span className="block text-[10px] text-muted-foreground">OF {c.of_ano}</span>}
    </span>
  );
}

function Tabela({
  colunas,
  linhas,
  vazio,
  onAbrir,
}: {
  colunas: string[];
  linhas: { id: string; celulas: React.ReactNode[]; destaque?: boolean; apagada?: boolean }[];
  vazio: string;
  onAbrir: (id: string) => void;
}) {
  if (!linhas.length) {
    return <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">{vazio}</div>;
  }
  return (
    <div className="overflow-x-auto rounded-xl border bg-card shadow-sm">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-muted/40 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
            {colunas.map((c, i) => (
              <th key={i} className={cn("py-2.5 pr-3", i === 0 && "pl-4")}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {linhas.map((l) => (
            <tr
              key={l.id}
              onClick={() => onAbrir(l.id)}
              className={cn(
                "cursor-pointer border-t hover:bg-muted/30",
                l.destaque && "bg-destructive/[0.04]",
                l.apagada && "opacity-60",
              )}
            >
              {l.celulas.map((cel, i) => (
                <td key={i} className={cn("py-2 pr-3 align-middle", i === 0 && "pl-4")}>
                  {cel}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
  const conhecido = STATUS_FRETE_OPCOES.some((o) => o.value === valor);
  if (readonly) return <span className="text-xs">{valor || "—"}</span>;
  return (
    <span onClick={(e) => e.stopPropagation()}>
      <Select value={valor || "LIBERADO"} onValueChange={onChange}>
        <SelectTrigger className="h-8 min-w-[170px] text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {STATUS_FRETE_OPCOES.map((o) => (
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
  onClose,
}: {
  c: PedidoConsolidado | null;
  draft: PedidoConsolidado | null;
  readonly: boolean;
  salvarRegra: boolean;
  onSalvarRegra: (v: boolean) => void;
  onPatch: (campos: Partial<PedidoConsolidado>) => void;
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
                <SeletorFrete valor={draft.status} readonly={readonly} onChange={(status) => onPatch({ status })} />
                {!readonly && draft.status !== c.status && (
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
