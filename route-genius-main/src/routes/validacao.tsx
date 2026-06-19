import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  ClipboardCheck,
  Loader2,
  ShieldAlert,
} from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  getStoredSessionId,
  useLogisticaSession,
} from "@/hooks/useLogisticaSession";
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/validacao")({
  head: () => ({ meta: [{ title: "Quarentena — Validação" }] }),
  component: ValidacaoPage,
});

const EDITABLE: (keyof PedidoConsolidado)[] = [
  "cliente",
  "bairro",
  "cidade",
  "cep",
  "representante",
];

function ValidacaoPage() {
  const navigate = useNavigate();
  const sessionId = getStoredSessionId();
  const { consolidadosQuery, confirmMutation, patchConsolidadoDebounced } =
    useLogisticaSession(sessionId);
  const [confirming, setConfirming] = useState(false);
  const [salvarRegras, setSalvarRegras] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts] = useState<Record<string, PedidoConsolidado>>({});

  const { data, isLoading, error } = consolidadosQuery;

  const stats = useMemo(() => {
    if (!data) return null;
    const total = data.consolidados.length;
    const enriquecidos = data.consolidados.filter((c) => c.enriquecido_mestre === "SIM").length;
    const liberados = data.consolidados.filter((c) => c.status === "LIBERADO").length;
    const revisoes = data.consolidados.filter(
      (c) => c.revisao_obrigatoria === COD_REVISAO_OBRIGATORIA,
    ).length;
    const processandoIa = data.consolidados.filter(
      (c) => c.status_ia === COD_PROCESSANDO_IA,
    ).length;
    return { total, enriquecidos, liberados, revisoes, processandoIa };
  }, [data]);

  const handleConfirm = async () => {
    if (!sessionId || !data) return;
    setConfirming(true);
    try {
      const regrasNovas: Record<string, string> = {};
      const memoriaNovas: Record<string, string> = {};
      for (const row of data.consolidados) {
        const key = row.numero_pedido_norm || row.numero_pedido;
        if (!salvarRegras[key]) continue;

        const draft = drafts[key] ?? row;
        const palavra = palavraChaveParaAprendizado(row);
        const chave = montarChaveRegraAprendizado(row.cliente_codigo, palavra);
        if (chave && draft.status) {
          regrasNovas[chave] = draft.status;
        }

        const chaveMemoria = montarChaveMemoriaOperacional(row.observacao_comercial);
        if (chaveMemoria && draft.status) {
          memoriaNovas[chaveMemoria] = draft.status;
        }
      }

      await confirmMutation.mutateAsync({ sid: sessionId, regrasNovas, memoriaNovas });
      navigate({ to: "/roteirizar" });
    } finally {
      setConfirming(false);
    }
  };

  const updateDraft = (pedidoKey: string, patch: Partial<PedidoConsolidado>) => {
    setDrafts((prev) => {
      const base =
        prev[pedidoKey] ??
        data?.consolidados.find((c) => (c.numero_pedido_norm || c.numero_pedido) === pedidoKey);
      if (!base) return prev;
      return { ...prev, [pedidoKey]: { ...base, ...patch } };
    });
  };

  if (!sessionId) {
    return (
      <div className="p-6 max-w-3xl">
        <div className="rounded-xl border border-warning/40 bg-warning/10 p-6 text-sm">
          Nenhuma sessão ativa. Faça o upload em{" "}
          <a href="/upload" className="font-semibold underline">
            Upload & Processamento
          </a>
          .
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Quarentena — Validação</h1>
          <p className="text-sm text-muted-foreground">
            Revise alertas automáticos, corrija o status de frete e ensine o sistema com regras
            locais.
          </p>
        </div>
        <button
          disabled={!data || data.validated || confirming}
          onClick={handleConfirm}
          className={cn(
            "inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold shadow-sm",
            data?.validated || confirming
              ? "bg-muted text-muted-foreground cursor-not-allowed"
              : "bg-accent text-accent-foreground hover:opacity-90",
          )}
        >
          {confirming ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <ClipboardCheck className="w-4 h-4" />
          )}
          Confirmar validação
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Carregando consolidados…
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-destructive/40 bg-destructive/10 p-4 text-sm flex gap-2">
          <ShieldAlert className="w-5 h-5 shrink-0" />
          {error.message}
        </div>
      )}

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          {[
            { label: "Consolidados", value: stats.total },
            { label: "Enriquecidos mestre", value: stats.enriquecidos },
            { label: "Liberados", value: stats.liberados },
            {
              label: "Revisão obrigatória",
              value: stats.revisoes,
              alert: stats.revisoes > 0,
            },
            {
              label: "Processando IA",
              value: stats.processandoIa,
              alert: stats.processandoIa > 0,
              highlight: stats.processandoIa > 0,
            },
            {
              label: "Status",
              value: data?.validated ? "Validado" : "Pendente",
            },
          ].map((s) => (
            <div
              key={s.label}
              className={cn(
                "rounded-lg border bg-card p-4",
                s.alert ? "border-destructive/50 bg-destructive/5" : "border-border",
                s.highlight && "border-primary/50 bg-primary/5",
              )}
            >
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                {s.label}
              </div>
              <div
                className={cn(
                  "text-xl font-bold mt-1 flex items-center gap-1.5",
                  s.alert && "text-destructive",
                  s.highlight && "text-primary",
                )}
              >
                {s.highlight && <Loader2 className="w-4 h-4 animate-spin" />}
                {s.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {data && (
        <TooltipProvider delayDuration={200}>
          <div className="bg-card border border-border rounded-xl shadow-sm overflow-x-auto">
            <table className="w-full text-sm min-w-[1100px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground bg-muted/40">
                <th className="px-4 py-2.5">Pedido</th>
                <th className="py-2.5 min-w-[140px]">Motivo Quarentena</th>
                <th className="py-2.5">Dt. Produção</th>
                <th className="py-2.5">Cliente</th>
                <th className="py-2.5">Bairro</th>
                <th className="py-2.5">Cidade</th>
                <th className="py-2.5">CEP</th>
                <th className="py-2.5">Representante</th>
                <th className="py-2.5">Rota</th>
                <th className="py-2.5 min-w-[180px]">Status (Frete)</th>
                <th className="py-2.5 min-w-[140px]">Aprender</th>
                <th className="py-2.5 pr-4">Mestre</th>
              </tr>
            </thead>
            <tbody>
              {data.consolidados.map((row) => {
                const pedidoKey = row.numero_pedido_norm || row.numero_pedido;
                return (
                  <EditableRow
                    key={pedidoKey}
                    row={row}
                    draft={drafts[pedidoKey] ?? row}
                    readonly={data.validated}
                    salvarRegra={!!salvarRegras[pedidoKey]}
                    onSalvarRegraChange={(checked) =>
                      setSalvarRegras((prev) => ({ ...prev, [pedidoKey]: checked }))
                    }
                    onPatch={(patch) => {
                      updateDraft(pedidoKey, patch);
                      patchConsolidadoDebounced(sessionId, pedidoKey, patch);
                    }}
                  />
                );
              })}
            </tbody>
            </table>
          </div>
        </TooltipProvider>
      )}
    </div>
  );
}

function EditableRow({
  row,
  draft,
  readonly,
  salvarRegra,
  onSalvarRegraChange,
  onPatch,
}: {
  row: PedidoConsolidado;
  draft: PedidoConsolidado;
  readonly: boolean;
  salvarRegra: boolean;
  onSalvarRegraChange: (checked: boolean) => void;
  onPatch: (patch: Partial<Pick<PedidoConsolidado, (typeof EDITABLE)[number] | "status">>) => void;
}) {
  const needsReview = row.revisao_obrigatoria === COD_REVISAO_OBRIGATORIA;
  const statusAlterado = draft.status !== row.status;
  const podeEnsinar = statusAlterado && !readonly;
  const processandoIa = row.status_ia === COD_PROCESSANDO_IA;
  const palavraAprendizado = palavraChaveParaAprendizado(row);

  const update = (field: (typeof EDITABLE)[number], value: string) => {
    onPatch({ [field]: value });
  };

  const updateStatus = (status: string) => {
    onPatch({ status });
  };

  const cell = (field: (typeof EDITABLE)[number]) =>
    readonly ? (
      <span>{draft[field]}</span>
    ) : (
      <input
        className="w-full min-w-[100px] px-2 py-1 rounded border border-input bg-background text-xs"
        value={String(draft[field] ?? "")}
        onChange={(e) => update(field, e.target.value)}
      />
    );

  return (
    <tr
      className={cn(
        "border-t border-border hover:bg-muted/20",
        needsReview && "bg-destructive/[0.04]",
      )}
    >
      <td className="px-4 py-2 font-mono text-xs">
        <div className="flex items-center gap-1.5">
          <span>{row.numero_pedido}</span>
          {processandoIa && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex text-muted-foreground" aria-label="Processando IA">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                </span>
              </TooltipTrigger>
              <TooltipContent side="top">Classificação em processamento pela IA…</TooltipContent>
            </Tooltip>
          )}
          {!processandoIa && row.flag_revisao_llm === "SIM" && row.sugestao_llm_status && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="inline-flex text-primary hover:text-primary/80"
                  aria-label="Sugestão da IA"
                >
                  <Brain className="w-3.5 h-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top">
                Sugestão da IA: {rotuloSugestaoLlm(row.sugestao_llm_status)}
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      </td>
      <td className="py-2">
        {needsReview ? (
          <div className="flex items-start gap-1.5 text-xs text-destructive max-w-[160px]">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span className="font-medium leading-snug">{row.motivo_quarentena}</span>
          </div>
        ) : (
          <span className="text-muted-foreground text-xs">—</span>
        )}
      </td>
      <td className="py-2 text-xs font-mono text-muted-foreground">
        {row.data_producao || "—"}
      </td>
      <td className="py-2">{cell("cliente")}</td>
      <td className="py-2">{cell("bairro")}</td>
      <td className="py-2">{cell("cidade")}</td>
      <td className="py-2">{cell("cep")}</td>
      <td className="py-2">{cell("representante")}</td>
      <td className="py-2 text-xs font-medium">{draft.rota_logistica}</td>
      <td className="py-2">
        {readonly ? (
          <StatusFreteBadge status={draft.status} />
        ) : (
          <Select
            value={
              STATUS_FRETE_OPCOES.some((o) => o.value === draft.status)
                ? draft.status
                : draft.status || "LIBERADO"
            }
            onValueChange={updateStatus}
          >
            <SelectTrigger className="h-8 text-xs min-w-[160px]">
              <SelectValue placeholder="Status frete" />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FRETE_OPCOES.map((opt) => (
                <SelectItem key={opt.value} value={opt.value} className="text-xs">
                  {opt.label}
                </SelectItem>
              ))}
              {!STATUS_FRETE_OPCOES.some((o) => o.value === draft.status) && draft.status && (
                <SelectItem value={draft.status} className="text-xs">
                  {draft.status}
                </SelectItem>
              )}
            </SelectContent>
          </Select>
        )}
      </td>
      <td className="py-2">
        {podeEnsinar ? (
          <label className="flex items-start gap-2 cursor-pointer text-[11px] leading-snug">
            <Checkbox
              checked={salvarRegra}
              onCheckedChange={(v) => onSalvarRegraChange(v === true)}
              className="mt-0.5"
            />
            <span>
              Salvar regra para este cliente
              <span className="block text-muted-foreground font-mono">
                {row.cliente_codigo}+{palavraAprendizado || "obs"}
              </span>
            </span>
          </label>
        ) : (
          <span className="text-muted-foreground text-xs">—</span>
        )}
      </td>
      <td className="py-2 pr-4">
        {row.enriquecido_mestre === "SIM" ? (
          <CheckCircle2 className="w-4 h-4 text-success" />
        ) : (
          <span className="text-muted-foreground text-xs">—</span>
        )}
      </td>
    </tr>
  );
}

function StatusFreteBadge({ status }: { status: string }) {
  const liberado = status === "LIBERADO";
  const hub = status === "ENTREGA_TERCEIRO_HUB";
  const retira = status === "RETIRA FOB" || status === "RETIRA_FOB";
  return (
    <span
      className={cn(
        "px-2 py-0.5 rounded text-[11px] font-medium",
        liberado && "bg-success/15 text-success",
        hub && "bg-primary/15 text-primary",
        retira && "bg-warning/15 text-warning-foreground",
        !liberado && !hub && !retira && "bg-destructive/10 text-destructive",
      )}
    >
      {status || "—"}
    </span>
  );
}
