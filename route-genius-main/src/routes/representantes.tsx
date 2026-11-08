import { createFileRoute } from "@tanstack/react-router";
import {
  Banknote,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Loader2,
  PhoneCall,
  Scale,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { getStoredSessionId, useLogisticaSession } from "@/hooks/useLogisticaSession";
import type { PedidoConsolidado, ResultadoConsulta } from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/representantes")({
  head: () => ({ meta: [{ title: "Pendências / Representante" }] }),
  component: RepresentantesPage,
});

const kg = (n: number) => `${n.toLocaleString("pt-BR")} kg`;
const temPend = (c: PedidoConsolidado, p: string) => (c.pendencias ?? []).includes(p as never);

function dataBR(texto?: string): string {
  if (!texto) return "";
  const iso = texto.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return iso ? `${iso[3]}/${iso[2]}/${iso[1]}` : texto;
}

function idLinha(c: PedidoConsolidado): string {
  return c.id_item || c.numero_pedido_norm || c.numero_pedido;
}

function linhaTexto(c: PedidoConsolidado): string {
  const of = c.of_ano ? ` OF ${c.of_ano}` : "";
  return `• ${c.cliente} — Pedido ${c.numero_pedido}${of} — ${kg(c.peso_kg)} — Dt. Produção ${c.data_producao}`;
}

function primeiroNome(rep: string): string {
  const n = rep.split(" ")[0] ?? rep;
  return n.charAt(0) + n.slice(1).toLowerCase();
}

/** Para o representante: "podemos carregar hoje?" */
function mensagemRepresentante(rep: string, linhas: PedidoConsolidado[], dataRef: string): string {
  const total = linhas.reduce((s, c) => s + (c.peso_kg || 0), 0);
  const hoje = dataRef ? ` hoje (${dataBR(dataRef)})` : " hoje";
  return (
    `Olá ${primeiroNome(rep)}, tudo bem?\n\n` +
    `Os materiais abaixo já estão prontos na expedição, mas a data de produção ainda não chegou. ` +
    `Podemos carregar${hoje}?\n\n${linhas.map(linhaTexto).join("\n")}\n\nTotal: ${kg(total)}\n\nObrigado!`
  );
}

/** Para o comercial: pedidos com pagamento antecipado prontos para sair. */
function mensagemComercial(rep: string, linhas: PedidoConsolidado[]): string {
  return (
    `Olá, tudo bem?\n\n` +
    `Os pedidos abaixo (representante ${rep}) são de pagamento antecipado e o material está pronto. ` +
    `Podem confirmar o pagamento e liberar o faturamento por e-mail?\n\n` +
    `${linhas.map(linhaTexto).join("\n")}\n\nObrigado!`
  );
}

async function copiarTexto(texto: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(texto);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = texto;
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  }
}

function BotaoCopiar({ texto, rotulo, disabled }: { texto: string; rotulo: string; disabled?: boolean }) {
  const [ok, setOk] = useState(false);
  return (
    <button
      type="button"
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
      onClick={async () => {
        if (await copiarTexto(texto)) {
          setOk(true);
          setTimeout(() => setOk(false), 2000);
        }
      }}
    >
      {ok ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
      {ok ? "Copiado!" : rotulo}
    </button>
  );
}

function SituacaoConsulta({ c }: { c: PedidoConsolidado }) {
  if (c.consulta_representante === "LIBERADO")
    return (
      <Badge className="bg-emerald-500/15 text-emerald-700 border border-emerald-500/40 hover:bg-emerald-500/15 gap-1">
        <CheckCircle2 className="w-3 h-3" /> Liberado
      </Badge>
    );
  if (c.consulta_representante === "NAO_LIBERADO")
    return (
      <Badge className="bg-destructive/10 text-destructive border border-destructive/30 hover:bg-destructive/10 gap-1">
        <XCircle className="w-3 h-3" /> Não liberado
      </Badge>
    );
  return (
    <Badge className="bg-amber-500/15 text-amber-700 border border-amber-500/40 hover:bg-amber-500/15 gap-1">
      <Clock className="w-3 h-3" /> Pendente
    </Badge>
  );
}

function OutrasPendencias({ c, exceto }: { c: PedidoConsolidado; exceto: string }) {
  const outras = (c.pendencias ?? []).filter((p) => p !== exceto);
  if (!outras.length) return null;
  const rotulo: Record<string, string> = {
    CONSULTA_REPRESENTANTE: "também: consultar representante",
    PAGAMENTO_ANTECIPADO: "também: aguardando comercial",
    PESO_ZERADO: "também: peso zerado",
  };
  return <div className="text-[10px] text-amber-700">{outras.map((p) => rotulo[p]).join(" · ")}</div>;
}

function RepresentantesPage() {
  const sessionId = getStoredSessionId();
  const { consolidadosQuery, consultaMutation, comercialMutation, pesoMutation } = useLogisticaSession(sessionId);
  const [mostrarRespondidos, setMostrarRespondidos] = useState(false);
  const [selecionados, setSelecionados] = useState<Record<string, boolean>>({});
  const [autorizadoPor, setAutorizadoPor] = useState<Record<string, string>>({});
  const [comercialPor, setComercialPor] = useState<Record<string, string>>({});
  const [comercialObs, setComercialObs] = useState<Record<string, string>>({});
  const [pesos, setPesos] = useState<Record<string, string>>({});
  const [aviso, setAviso] = useState("");

  const todas = consolidadosQuery.data?.consolidados ?? [];
  const dataRef = todas[0]?.data_referencia ?? "";

  const pesoZerado = todas.filter((c) => temPend(c, "PESO_ZERADO"));

  const grupos = useMemo(() => {
    const mapa = new Map<string, { consulta: PedidoConsolidado[]; comercial: PedidoConsolidado[] }>();
    const grupo = (rep: string) => {
      if (!mapa.has(rep)) mapa.set(rep, { consulta: [], comercial: [] });
      return mapa.get(rep)!;
    };
    for (const c of todas) {
      const rep = c.representante || "NÃO IDENTIFICADO";
      const consultaRespondida = !!c.consulta_representante && !temPend(c, "CONSULTA_REPRESENTANTE");
      if (temPend(c, "CONSULTA_REPRESENTANTE") || (mostrarRespondidos && consultaRespondida)) {
        grupo(rep).consulta.push(c);
      }
      if (temPend(c, "PAGAMENTO_ANTECIPADO") || (mostrarRespondidos && c.liberacao_comercial === "LIBERADO")) {
        grupo(rep).comercial.push(c);
      }
    }
    const peso = (l: PedidoConsolidado[]) => l.reduce((s, c) => s + (c.peso_kg || 0), 0);
    return [...mapa.entries()]
      .map(([rep, g]) => ({ rep, ...g }))
      .sort((a, b) => peso([...b.consulta, ...b.comercial]) - peso([...a.consulta, ...a.comercial]));
  }, [todas, mostrarRespondidos]);

  const nConsulta = todas.filter((c) => temPend(c, "CONSULTA_REPRESENTANTE")).length;
  const nComercial = todas.filter((c) => temPend(c, "PAGAMENTO_ANTECIPADO")).length;
  const pesoParado = todas
    .filter((c) => (c.pendencias ?? []).length)
    .reduce((s, c) => s + (c.peso_kg || 0), 0);

  const limparSelecao = (ids: string[]) =>
    setSelecionados((prev) => {
      const next = { ...prev };
      ids.forEach((id) => delete next[id]);
      return next;
    });

  const responderConsulta = async (rep: string, ids: string[], resultado: ResultadoConsulta) => {
    if (!sessionId || !ids.length) return;
    const r = await consultaMutation.mutateAsync({
      sid: sessionId,
      body: { ids, resultado, autorizado_por: autorizadoPor[rep] ?? rep },
    });
    setAviso(r.message);
    limparSelecao(ids);
  };

  const responderComercial = async (rep: string, ids: string[], resultado: "LIBERADO" | "AGUARDANDO") => {
    if (!sessionId || !ids.length) return;
    const r = await comercialMutation.mutateAsync({
      sid: sessionId,
      body: { ids, resultado, liberado_por: comercialPor[rep] ?? "", obs: comercialObs[rep] ?? "" },
    });
    setAviso(r.message);
    limparSelecao(ids);
  };

  const salvarPeso = async (c: PedidoConsolidado) => {
    const valor = Number(pesos[idLinha(c)]);
    if (!sessionId || !(valor > 0)) return;
    const r = await pesoMutation.mutateAsync({ sid: sessionId, body: { id: idLinha(c), peso_kg: valor } });
    setAviso(r.message);
  };

  if (!sessionId) {
    return <div className="p-6 text-sm text-muted-foreground">Nenhuma sessão ativa. Execute o upload primeiro.</div>;
  }

  const ocupado = consultaMutation.isPending || comercialMutation.isPending || pesoMutation.isPending;
  const marcadosDe = (lista: PedidoConsolidado[]) => lista.map(idLinha).filter((id) => selecionados[id]);
  const checkbox = (c: PedidoConsolidado) => (
    <Checkbox
      checked={!!selecionados[idLinha(c)]}
      onCheckedChange={(v) => setSelecionados((p) => ({ ...p, [idLinha(c)]: v === true }))}
    />
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <PhoneCall className="w-6 h-6" /> Pendências / Representante
          </h1>
          <p className="text-sm text-muted-foreground max-w-3xl">
            Linhas paradas até alguém agir{dataRef ? ` — solicitação de ${dataBR(dataRef)}` : ""}. Consulta ao
            representante só quando a logística leva (frota própria ou levar na transportadora); retira e
            transportadora que coleta não passam por aqui.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={mostrarRespondidos} onCheckedChange={(v) => setMostrarRespondidos(v === true)} />
          Mostrar já respondidos
        </label>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 max-w-3xl">
        {[
          ["Consultar representante", nConsulta],
          ["Aguardando comercial", nComercial],
          ["Peso zerado", pesoZerado.length],
          ["Peso parado", kg(pesoParado)],
        ].map(([rotulo, valor]) => (
          <div key={String(rotulo)} className="rounded-lg border bg-card p-3">
            <div className="text-xs text-muted-foreground">{rotulo}</div>
            <div className="text-xl font-bold">{valor}</div>
          </div>
        ))}
      </div>

      {aviso && (
        <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm">{aviso}</div>
      )}

      {consolidadosQuery.isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Carregando…
        </div>
      )}

      {pesoZerado.length > 0 && (
        <section className="rounded-xl border border-amber-500/40 bg-card shadow-sm">
          <header className="flex items-center gap-2 border-b px-4 py-3">
            <Scale className="w-4 h-4 text-amber-600" />
            <div>
              <div className="font-semibold">Peso zerado — a logística precisa informar o peso</div>
              <div className="text-xs text-muted-foreground">
                A linha só entra na rota depois que o peso real for informado.
              </div>
            </div>
          </header>
          <table className="w-full text-sm">
            <tbody>
              {pesoZerado.map((c) => (
                <tr key={idLinha(c)} className="border-t">
                  <td className="px-4 py-2 font-medium">
                    {c.cliente}
                    <OutrasPendencias c={c} exceto="PESO_ZERADO" />
                  </td>
                  <td className="py-2 font-mono text-xs">
                    {c.numero_pedido}
                    {c.of_ano && <span className="text-muted-foreground"> · OF {c.of_ano}</span>}
                  </td>
                  <td className="py-2 text-xs text-muted-foreground">{c.representante}</td>
                  <td className="py-2 text-xs text-muted-foreground max-w-[280px] truncate" title={c.observacao_comercial}>
                    {c.observacao_comercial}
                  </td>
                  <td className="py-2 pr-4">
                    <div className="flex items-center justify-end gap-2">
                      <input
                        type="number"
                        min={0.1}
                        step="0.1"
                        placeholder="kg"
                        className="w-28 rounded-md border border-input bg-background px-2 py-1.5 font-mono text-sm"
                        value={pesos[idLinha(c)] ?? ""}
                        onChange={(e) => setPesos((p) => ({ ...p, [idLinha(c)]: e.target.value }))}
                        onKeyDown={(e) => e.key === "Enter" && void salvarPeso(c)}
                      />
                      <button
                        type="button"
                        disabled={ocupado || !(Number(pesos[idLinha(c)]) > 0)}
                        className="rounded-md bg-accent px-3 py-1.5 text-sm text-accent-foreground disabled:opacity-50"
                        onClick={() => void salvarPeso(c)}
                      >
                        Salvar peso
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {!consolidadosQuery.isLoading && grupos.length === 0 && pesoZerado.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          Nenhuma linha parada. Tudo pode seguir para a rota.
        </div>
      )}

      <div className="space-y-5">
        {grupos.map(({ rep, consulta, comercial }) => {
          const consultaPend = consulta.filter((c) => temPend(c, "CONSULTA_REPRESENTANTE"));
          const comercialPend = comercial.filter((c) => temPend(c, "PAGAMENTO_ANTECIPADO"));
          const marcConsulta = marcadosDe(consulta);
          const marcComercial = marcadosDe(comercial);
          const alvoConsulta = marcConsulta.length ? marcConsulta : consultaPend.map(idLinha);
          const alvoComercial = marcComercial.length ? marcComercial : comercialPend.map(idLinha);
          return (
            <section key={rep} className="rounded-xl border bg-card shadow-sm">
              <header className="border-b px-4 py-3">
                <div className="font-semibold">{rep}</div>
                <div className="text-xs text-muted-foreground">
                  {consultaPend.length} para consultar · {comercialPend.length} aguardando comercial
                </div>
              </header>

              {consulta.length > 0 && (
                <div className="border-b last:border-b-0">
                  <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 bg-muted/30">
                    <div className="text-sm font-medium flex items-center gap-1.5">
                      <PhoneCall className="w-4 h-4" /> Pode carregar hoje?
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <BotaoCopiar
                        rotulo="Copiar mensagem"
                        disabled={!consultaPend.length}
                        texto={mensagemRepresentante(rep, consultaPend, dataRef)}
                      />
                      <input
                        className="w-40 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                        placeholder="Autorizado por"
                        value={autorizadoPor[rep] ?? rep}
                        onChange={(e) => setAutorizadoPor((p) => ({ ...p, [rep]: e.target.value }))}
                      />
                      <button
                        type="button"
                        disabled={ocupado || !alvoConsulta.length}
                        className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-50"
                        onClick={() => void responderConsulta(rep, alvoConsulta, "LIBERADO")}
                      >
                        Liberar {marcConsulta.length ? `(${marcConsulta.length})` : "todos"}
                      </button>
                      <button
                        type="button"
                        disabled={ocupado || !alvoConsulta.length}
                        className="rounded-md border border-destructive/40 px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 disabled:opacity-50"
                        onClick={() => void responderConsulta(rep, alvoConsulta, "NAO_LIBERADO")}
                      >
                        Não liberar
                      </button>
                    </div>
                  </div>
                  <table className="w-full text-sm">
                    <tbody>
                      {consulta.map((c) => (
                        <tr
                          key={idLinha(c)}
                          className={cn("border-t", !temPend(c, "CONSULTA_REPRESENTANTE") && "opacity-60")}
                        >
                          <td className="w-10 px-4 py-2">{checkbox(c)}</td>
                          <td className="py-2 font-medium">
                            {c.cliente}
                            <OutrasPendencias c={c} exceto="CONSULTA_REPRESENTANTE" />
                          </td>
                          <td className="py-2 font-mono text-xs">
                            {c.numero_pedido}
                            {c.of_ano && <span className="text-muted-foreground"> · OF {c.of_ano}</span>}
                          </td>
                          <td className="py-2 text-right font-mono">{kg(c.peso_kg)}</td>
                          <td className="py-2 pl-6 font-mono text-xs">Dt. Prod. {c.data_producao}</td>
                          <td className="py-2 text-xs">{c.dias_uteis_antecedencia} dias úteis</td>
                          <td className="py-2 pr-4">
                            <div className="flex items-center gap-2">
                              <SituacaoConsulta c={c} />
                              {c.consulta_representante && (
                                <button
                                  type="button"
                                  className="text-[11px] text-muted-foreground underline"
                                  onClick={() => void responderConsulta(rep, [idLinha(c)], "PENDENTE")}
                                >
                                  desfazer
                                </button>
                              )}
                            </div>
                            {c.consulta_em && (
                              <div className="text-[10px] text-muted-foreground mt-0.5">
                                {c.consulta_em}
                                {c.representante_autorizou ? ` · ${c.representante_autorizou}` : ""}
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {comercial.length > 0 && (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 bg-muted/30">
                    <div className="text-sm font-medium flex items-center gap-1.5">
                      <Banknote className="w-4 h-4" /> Pagamento antecipado — aguardando liberação do comercial
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <BotaoCopiar
                        rotulo="Copiar e-mail p/ comercial"
                        disabled={!comercialPend.length}
                        texto={mensagemComercial(rep, comercialPend)}
                      />
                      <input
                        className="w-36 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                        placeholder="Liberado por"
                        value={comercialPor[rep] ?? ""}
                        onChange={(e) => setComercialPor((p) => ({ ...p, [rep]: e.target.value }))}
                      />
                      <input
                        className="w-48 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                        placeholder="E-mail (assunto / data)"
                        value={comercialObs[rep] ?? ""}
                        onChange={(e) => setComercialObs((p) => ({ ...p, [rep]: e.target.value }))}
                      />
                      <button
                        type="button"
                        disabled={ocupado || !alvoComercial.length || !(comercialPor[rep] ?? "").trim()}
                        title={!(comercialPor[rep] ?? "").trim() ? "Informe quem do comercial liberou" : undefined}
                        className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-50"
                        onClick={() => void responderComercial(rep, alvoComercial, "LIBERADO")}
                      >
                        Comercial liberou {marcComercial.length ? `(${marcComercial.length})` : ""}
                      </button>
                    </div>
                  </div>
                  <table className="w-full text-sm">
                    <tbody>
                      {comercial.map((c) => (
                        <tr
                          key={idLinha(c)}
                          className={cn("border-t", !temPend(c, "PAGAMENTO_ANTECIPADO") && "opacity-60")}
                        >
                          <td className="w-10 px-4 py-2">{checkbox(c)}</td>
                          <td className="py-2 font-medium">
                            {c.cliente}
                            <OutrasPendencias c={c} exceto="PAGAMENTO_ANTECIPADO" />
                          </td>
                          <td className="py-2 font-mono text-xs">
                            {c.numero_pedido}
                            {c.of_ano && <span className="text-muted-foreground"> · OF {c.of_ano}</span>}
                          </td>
                          <td className="py-2 text-right font-mono">{kg(c.peso_kg)}</td>
                          <td className="py-2 pl-6 text-xs text-muted-foreground">{c.status}</td>
                          <td className="py-2 pr-4">
                            {c.liberacao_comercial === "LIBERADO" ? (
                              <div className="flex items-center gap-2">
                                <Badge className="bg-emerald-500/15 text-emerald-700 border border-emerald-500/40 hover:bg-emerald-500/15 gap-1">
                                  <CheckCircle2 className="w-3 h-3" /> Comercial liberou
                                </Badge>
                                <button
                                  type="button"
                                  className="text-[11px] text-muted-foreground underline"
                                  onClick={() => void responderComercial(rep, [idLinha(c)], "AGUARDANDO")}
                                >
                                  desfazer
                                </button>
                              </div>
                            ) : (
                              <Badge className="bg-amber-500/15 text-amber-700 border border-amber-500/40 hover:bg-amber-500/15 gap-1">
                                <Clock className="w-3 h-3" /> Aguardando comercial
                              </Badge>
                            )}
                            {c.liberacao_comercial_em && (
                              <div className="text-[10px] text-muted-foreground mt-0.5">
                                {c.liberacao_comercial_em} · {c.liberacao_comercial_por}
                                {c.liberacao_comercial_obs ? ` · ${c.liberacao_comercial_obs}` : ""}
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
