import { useEffect, useState } from "react";
import { Search, Loader2 } from "lucide-react";
import { buscarHistorico } from "@/lib/api-client";
import type { HistoricoRegistro } from "@/lib/logistica-types";

export function HistoricoSearch() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [resultados, setResultados] = useState<HistoricoRegistro[]>([]);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    if (debounced.length < 2) {
      setResultados([]);
      setOpen(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    buscarHistorico(debounced)
      .then((resp) => {
        if (!cancelled) {
          setResultados(resp.resultados);
          setOpen(resp.total > 0);
        }
      })
      .catch(() => {
        if (!cancelled) setResultados([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debounced]);

  return (
    <div className="relative hidden md:block">
      <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
      {loading && <Loader2 className="w-3 h-3 absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-muted-foreground" />}
      <input
        placeholder="Buscar pedido, cliente (histórico)…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => debounced.length >= 2 && resultados.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className="pl-9 pr-8 py-2 text-sm rounded-md border border-input bg-background w-72 outline-none focus:ring-2 focus:ring-ring"
      />
      {open && resultados.length > 0 && (
        <div className="absolute top-full mt-1 right-0 w-96 max-h-72 overflow-auto rounded-md border border-border bg-popover shadow-lg z-50">
          {resultados.map((r) => (
            <div key={r.hash_id} className="px-3 py-2 border-b border-border last:border-0 hover:bg-muted/50 text-xs">
              <div className="font-semibold">{r.numero_pedido} · {r.cliente}</div>
              <div className="text-muted-foreground mt-0.5">
                Status: {r.status_final || "—"} · Entrega: {r.data_entrega || "—"}
              </div>
              <div className="text-[10px] text-muted-foreground/80">{r.arquivo_historico}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
