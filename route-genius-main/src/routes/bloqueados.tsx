import { createFileRoute } from "@tanstack/react-router";
import { AlertTriangle, Loader2 } from "lucide-react";
import { useMemo, useState } from "react";

import {
  getStoredSessionId,
  useLogisticaSession,
} from "@/hooks/useLogisticaSession";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const Route = createFileRoute("/bloqueados")({
  head: () => ({ meta: [{ title: "Bloqueados & Pendências" }] }),
  component: BloqueadosPage,
});

interface BacklogRow {
  numero_pedido: string;
  cliente: string;
  representante: string;
  cidade_destino: string;
  rota_logistica: string;
  peso_kg: string;
  motivo: string;
  origem: "backlog" | "consolidado";
}

function BloqueadosPage() {
  const sessionId = getStoredSessionId();
  const { consolidadosQuery, roteirizacaoQuery } = useLogisticaSession(sessionId);
  const [filtroRep, setFiltroRep] = useState("TODOS");

  const rows = useMemo(() => {
    const result: BacklogRow[] = [];
    const roteirizacao = roteirizacaoQuery.data;
    const consolidados = consolidadosQuery.data;

    if (roteirizacao) {
      for (const b of roteirizacao.backlog_futuro ?? []) {
        result.push({
          numero_pedido: b.numero_pedido ?? "",
          cliente: b.cliente ?? "",
          representante: b.representante ?? "NÃO IDENTIFICADO",
          cidade_destino: b.cidade_destino ?? "",
          rota_logistica: b.rota_logistica ?? "",
          peso_kg: b.peso_kg ?? "0",
          motivo: `BACKLOG FUTURO${b.data_prevista_recebimento ? ` — ${b.data_prevista_recebimento}` : ""}`,
          origem: "backlog_futuro",
        });
      }
      for (const b of roteirizacao.backlog) {
        result.push({
          numero_pedido: b.numero_pedido ?? "",
          cliente: b.cliente ?? "",
          representante: b.representante ?? "NÃO IDENTIFICADO",
          cidade_destino: b.cidade_destino ?? "",
          rota_logistica: b.rota_logistica ?? "",
          peso_kg: b.peso_kg ?? "0",
          motivo: b.motivo ?? "BACKLOG",
          origem: "backlog",
        });
      }
    }

    if (consolidados) {
      for (const c of consolidados.consolidados) {
        if (c.status === "LIBERADO") continue;
        if (result.some((r) => r.numero_pedido === c.numero_pedido)) continue;
        result.push({
          numero_pedido: c.numero_pedido,
          cliente: c.cliente,
          representante: c.representante || "NÃO IDENTIFICADO",
          cidade_destino: c.cidade_destino || c.cidade,
          rota_logistica: c.rota_logistica,
          peso_kg: String(c.peso_kg),
          motivo: `${c.status}${c.motivo_bloqueio ? ` — ${c.motivo_bloqueio}` : ""}`,
          origem: "consolidado",
        });
      }
    }

    return result;
  }, [consolidadosQuery.data, roteirizacaoQuery.data]);

  const representantes = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => {
      if (r.representante) set.add(r.representante);
    });
    return ["TODOS", ...Array.from(set).sort()];
  }, [rows]);

  const filtered =
    filtroRep === "TODOS" ? rows : rows.filter((r) => r.representante === filtroRep);

  if (!sessionId) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Nenhuma sessão ativa. Execute o upload primeiro.
      </div>
    );
  }

  const loading = consolidadosQuery.isLoading || roteirizacaoQuery.isLoading;

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Bloqueados & Pendências</h1>
          <p className="text-sm text-muted-foreground">
            Backlog operacional + pedidos não liberados na ingestão
          </p>
        </div>
        <div className="w-64">
          <label className="text-xs text-muted-foreground mb-1 block">Representante</label>
          <Select value={filtroRep} onValueChange={setFiltroRep}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {representantes.map((r) => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Carregando…
        </div>
      )}

      {filtered.length === 0 && !loading ? (
        <div className="rounded-xl border border-success/30 bg-success/10 p-6 text-sm flex gap-2">
          <AlertTriangle className="w-5 h-5 text-success" />
          Nenhum bloqueio ou item no backlog para os filtros selecionados.
        </div>
      ) : (
        <div className="bg-card border border-border rounded-xl overflow-x-auto">
          <table className="w-full text-sm min-w-[800px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground bg-muted/40">
                <th className="px-4 py-2.5">Pedido</th>
                <th className="py-2.5">Cliente</th>
                <th className="py-2.5">Representante</th>
                <th className="py-2.5">Cidade</th>
                <th className="py-2.5">Rota</th>
                <th className="py-2.5 text-right">Peso</th>
                <th className="py-2.5 pr-4">Motivo</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={`${r.origem}-${r.numero_pedido}`} className="border-t border-border">
                  <td className="px-4 py-3 font-mono text-xs">{r.numero_pedido}</td>
                  <td className="py-3">{r.cliente}</td>
                  <td className="py-3 text-xs">{r.representante}</td>
                  <td className="py-3">{r.cidade_destino}</td>
                  <td className="py-3 text-xs">{r.rota_logistica}</td>
                  <td className="py-3 text-right font-mono">{r.peso_kg} kg</td>
                  <td className="py-3 pr-4 text-xs">{r.motivo}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
