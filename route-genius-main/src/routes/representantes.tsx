import { createFileRoute } from "@tanstack/react-router";
import { Check, CheckCircle2, Clock, Copy, Loader2, PhoneCall, XCircle } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { getStoredSessionId, useLogisticaSession } from "@/hooks/useLogisticaSession";
import type { PedidoConsolidado, ResultadoConsulta } from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/representantes")({
  head: () => ({ meta: [{ title: "Consultar Representante" }] }),
  component: RepresentantesPage,
});

const kg = (n: number) => `${n.toLocaleString("pt-BR")} kg`;

function dataBR(texto?: string): string {
  if (!texto) return "";
  const iso = texto.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return `${iso[3]}/${iso[2]}/${iso[1]}`;
  return texto;
}

function idLinha(c: PedidoConsolidado): string {
  return c.id_item || c.numero_pedido_norm || c.numero_pedido;
}

/** Texto pronto para WhatsApp/e-mail com todos os pedidos pendentes do representante. */
function montarMensagem(rep: string, linhas: PedidoConsolidado[], dataRef: string): string {
  const primeiroNome = rep.split(" ")[0] ?? rep;
  const nome = primeiroNome.charAt(0) + primeiroNome.slice(1).toLowerCase();
  const itens = linhas
    .map((c) => {
      const of = c.of_ano ? ` OF ${c.of_ano}` : "";
      return `• ${c.cliente} — Pedido ${c.numero_pedido}${of} — ${kg(c.peso_kg)} — Dt. Produção ${c.data_producao}`;
    })
    .join("\n");
  const total = linhas.reduce((s, c) => s + (c.peso_kg || 0), 0);
  const hoje = dataRef ? ` hoje (${dataBR(dataRef)})` : " hoje";
  return (
    `Olá ${nome}, tudo bem?\n\n` +
    `Os materiais abaixo já estão prontos na expedição, mas a data de produção ainda não chegou. ` +
    `Podemos carregar${hoje}?\n\n${itens}\n\nTotal: ${kg(total)}\n\nObrigado!`
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

function SituacaoBadge({ c }: { c: PedidoConsolidado }) {
  const s = c.consulta_representante;
  if (s === "LIBERADO")
    return (
      <Badge className="bg-emerald-500/15 text-emerald-700 border border-emerald-500/40 hover:bg-emerald-500/15 gap-1">
        <CheckCircle2 className="w-3 h-3" /> Liberado
      </Badge>
    );
  if (s === "NAO_LIBERADO")
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

function RepresentantesPage() {
  const sessionId = getStoredSessionId();
  const { consolidadosQuery, consultaMutation } = useLogisticaSession(sessionId);
  const [mostrarRespondidos, setMostrarRespondidos] = useState(false);
  const [selecionados, setSelecionados] = useState<Record<string, boolean>>({});
  const [autorizadoPor, setAutorizadoPor] = useState<Record<string, string>>({});
  const [copiado, setCopiado] = useState<string | null>(null);
  const [aviso, setAviso] = useState("");

  const linhas = useMemo(
    () => (consolidadosQuery.data?.consolidados ?? []).filter((c) => !!c.consulta_representante),
    [consolidadosQuery.data],
  );
  const dataRef = linhas[0]?.data_referencia ?? "";

  const grupos = useMemo(() => {
    const mapa = new Map<string, PedidoConsolidado[]>();
    for (const c of linhas) {
      if (!mostrarRespondidos && c.consulta_representante !== "PENDENTE") continue;
      const rep = c.representante || "NÃO IDENTIFICADO";
      mapa.set(rep, [...(mapa.get(rep) ?? []), c]);
    }
    return [...mapa.entries()]
      .map(([rep, itens]) => ({
        rep,
        itens: itens.sort((a, b) => (a.data_producao || "").localeCompare(b.data_producao || "")),
        pendentes: itens.filter((c) => c.consulta_representante === "PENDENTE"),
      }))
      .sort(
        (a, b) =>
          b.pendentes.reduce((s, c) => s + c.peso_kg, 0) - a.pendentes.reduce((s, c) => s + c.peso_kg, 0),
      );
  }, [linhas, mostrarRespondidos]);

  const pendentes = linhas.filter((c) => c.consulta_representante === "PENDENTE");
  const totalPendenteKg = pendentes.reduce((s, c) => s + (c.peso_kg || 0), 0);

  const responder = async (rep: string, ids: string[], resultado: ResultadoConsulta) => {
    if (!sessionId || ids.length === 0) return;
    const resp = await consultaMutation.mutateAsync({
      sid: sessionId,
      body: { ids, resultado, autorizado_por: autorizadoPor[rep] ?? rep },
    });
    setAviso(resp.message);
    setSelecionados((prev) => {
      const next = { ...prev };
      ids.forEach((id) => delete next[id]);
      return next;
    });
  };

  if (!sessionId) {
    return <div className="p-6 text-sm text-muted-foreground">Nenhuma sessão ativa. Execute o upload primeiro.</div>;
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <PhoneCall className="w-6 h-6" /> Consultar Representante
          </h1>
          <p className="text-sm text-muted-foreground max-w-2xl">
            Material pronto com Dt. Produção a 3 dias úteis ou mais
            {dataRef ? ` de ${dataBR(dataRef)}` : ""}. Só entra na rota depois do OK do representante.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={mostrarRespondidos} onCheckedChange={(v) => setMostrarRespondidos(v === true)} />
          Mostrar já respondidos
        </label>
      </div>

      <div className="grid grid-cols-3 gap-3 max-w-xl">
        <div className="rounded-lg border bg-card p-3">
          <div className="text-xs text-muted-foreground">Linhas pendentes</div>
          <div className="text-xl font-bold">{pendentes.length}</div>
        </div>
        <div className="rounded-lg border bg-card p-3">
          <div className="text-xs text-muted-foreground">Peso parado</div>
          <div className="text-xl font-bold">{kg(totalPendenteKg)}</div>
        </div>
        <div className="rounded-lg border bg-card p-3">
          <div className="text-xs text-muted-foreground">Representantes</div>
          <div className="text-xl font-bold">{new Set(pendentes.map((c) => c.representante)).size}</div>
        </div>
      </div>

      {aviso && (
        <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm">{aviso}</div>
      )}

      {consolidadosQuery.isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Carregando…
        </div>
      )}

      {!consolidadosQuery.isLoading && grupos.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          Nenhum pedido aguardando o representante.
        </div>
      )}

      <div className="space-y-5">
        {grupos.map(({ rep, itens, pendentes: pend }) => {
          const ids = itens.map(idLinha);
          const marcados = ids.filter((id) => selecionados[id]);
          const alvo = marcados.length ? marcados : pend.map(idLinha);
          const pesoPend = pend.reduce((s, c) => s + c.peso_kg, 0);
          const ocupado = consultaMutation.isPending;
          return (
            <section key={rep} className="rounded-xl border bg-card shadow-sm">
              <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
                <div>
                  <div className="font-semibold">{rep}</div>
                  <div className="text-xs text-muted-foreground">
                    {pend.length} pendente(s) · {kg(pesoPend)}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={pend.length === 0}
                    className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
                    onClick={async () => {
                      if (await copiarTexto(montarMensagem(rep, pend, dataRef))) {
                        setCopiado(rep);
                        setTimeout(() => setCopiado(null), 2000);
                      }
                    }}
                  >
                    {copiado === rep ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                    {copiado === rep ? "Copiado!" : "Copiar mensagem"}
                  </button>
                  <input
                    className="w-44 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                    placeholder="Autorizado por"
                    value={autorizadoPor[rep] ?? rep}
                    onChange={(e) => setAutorizadoPor((p) => ({ ...p, [rep]: e.target.value }))}
                  />
                  <button
                    type="button"
                    disabled={ocupado || alvo.length === 0}
                    className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-50"
                    onClick={() => void responder(rep, alvo, "LIBERADO")}
                  >
                    Liberar {marcados.length ? `selecionados (${marcados.length})` : "todos pendentes"}
                  </button>
                  <button
                    type="button"
                    disabled={ocupado || alvo.length === 0}
                    className="rounded-md border border-destructive/40 px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 disabled:opacity-50"
                    onClick={() => void responder(rep, alvo, "NAO_LIBERADO")}
                  >
                    Não liberar
                  </button>
                </div>
              </header>
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr className="text-left">
                    <th className="w-10 px-4 py-2" />
                    <th className="py-2">Cliente</th>
                    <th className="py-2">Pedido · OF</th>
                    <th className="py-2 text-right">Peso</th>
                    <th className="py-2 pl-6">Dt. Produção</th>
                    <th className="py-2">Antecedência</th>
                    <th className="py-2">Frete</th>
                    <th className="py-2 pr-4">Situação</th>
                  </tr>
                </thead>
                <tbody>
                  {itens.map((c) => {
                    const id = idLinha(c);
                    return (
                      <tr
                        key={id}
                        className={cn(
                          "border-t",
                          c.consulta_representante !== "PENDENTE" && "opacity-60",
                        )}
                      >
                        <td className="px-4 py-2">
                          <Checkbox
                            checked={!!selecionados[id]}
                            onCheckedChange={(v) => setSelecionados((p) => ({ ...p, [id]: v === true }))}
                          />
                        </td>
                        <td className="py-2 font-medium">{c.cliente}</td>
                        <td className="py-2 font-mono text-xs">
                          {c.numero_pedido}
                          {c.of_ano && <span className="text-muted-foreground"> · OF {c.of_ano}</span>}
                        </td>
                        <td className="py-2 text-right font-mono">{kg(c.peso_kg)}</td>
                        <td className="py-2 pl-6 font-mono text-xs">{c.data_producao}</td>
                        <td className="py-2 text-xs">{c.dias_uteis_antecedencia} dias úteis</td>
                        <td className="py-2 text-xs text-muted-foreground">{c.status}</td>
                        <td className="py-2 pr-4">
                          <div className="flex items-center gap-2">
                            <SituacaoBadge c={c} />
                            {c.consulta_representante !== "PENDENTE" && (
                              <button
                                type="button"
                                className="text-[11px] text-muted-foreground underline"
                                onClick={() => void responder(rep, [id], "PENDENTE")}
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
                    );
                  })}
                </tbody>
              </table>
            </section>
          );
        })}
      </div>
    </div>
  );
}
