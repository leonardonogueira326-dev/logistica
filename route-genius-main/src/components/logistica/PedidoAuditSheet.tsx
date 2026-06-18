import { MapPin, AlertTriangle, FileText, CalendarClock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { PedidoConsolidado } from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

export function PedidoAuditSheet({
  pedido,
  open,
  onOpenChange,
}: {
  pedido: PedidoConsolidado | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  if (!pedido) return null;

  const enriquecido = pedido.enriquecido_mestre === "SIM";
  const enderecoParts = [
    pedido.bairro_destino || pedido.bairro,
    pedido.cidade_destino || pedido.cidade,
    pedido.estado_destino || pedido.estado,
  ].filter(Boolean);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="font-mono text-base">{pedido.numero_pedido}</SheetTitle>
          <SheetDescription className="text-left">
            <span className="font-semibold text-foreground">{pedido.cliente}</span>
          </SheetDescription>
          <div className="pt-2">
            <StatusBadge status={pedido.status} />
          </div>
          {pedido.data_producao?.trim() && (
            <div className="mt-3 rounded-lg border-2 border-primary/40 bg-primary/10 px-4 py-3">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-primary">
                <CalendarClock className="w-4 h-4" />
                Data de Produção
              </div>
              <p className="mt-1 text-2xl font-bold font-mono text-foreground">
                {pedido.data_producao}
              </p>
              <p className="text-[11px] text-muted-foreground mt-1">
                Material pronto para embarque nesta data
              </p>
            </div>
          )}
        </SheetHeader>

        <div className="mt-6 space-y-6">
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-2">
              <MapPin className="w-3.5 h-3.5" /> Dados Geográficos
            </h3>
            <dl className="space-y-2 text-sm">
              <Row label="Endereço / Região" value={enderecoParts.join(" · ") || "—"} />
              <Row label="Bairro" value={pedido.bairro_destino || pedido.bairro} />
              <Row label="Cidade" value={pedido.cidade_destino || pedido.cidade} />
              <Row label="CEP" value={pedido.cep_destino || pedido.cep} />
              <Row label="Representante" value={pedido.representante} />
              <Row label="Rota logística" value={pedido.rota_logistica} />
            </dl>
            <div className="mt-3">
              {enriquecido ? (
                <Badge variant="outline" className="bg-success/10 text-success border-success/30">
                  Fonte: Mestre CSV
                </Badge>
              ) : (
                <Badge variant="outline" className="bg-warning/10 text-warning-foreground border-warning/40">
                  <AlertTriangle className="w-3 h-3 mr-1" />
                  Fonte: PDF (Fallback)
                </Badge>
              )}
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
              Dados Comerciais
            </h3>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg border border-border p-3">
                <dt className="text-xs text-muted-foreground">Peso</dt>
                <dd className="text-lg font-bold font-mono">
                  {pedido.peso_kg.toLocaleString("pt-BR")} kg
                </dd>
              </div>
              <div className="rounded-lg border border-border p-3">
                <dt className="text-xs text-muted-foreground">Valor TT</dt>
                <dd className="text-lg font-bold font-mono">
                  R$ {pedido.valor_tt.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                </dd>
              </div>
            </dl>
            {(pedido.is_spyder === "SIM" || pedido.is_dimensao_longa === "SIM") && (
              <div className="mt-2 flex gap-2">
                {pedido.is_spyder === "SIM" && (
                  <Badge variant="destructive">SPYDER</Badge>
                )}
                {pedido.is_dimensao_longa === "SIM" && (
                  <Badge variant="destructive">DIMENSÃO LONGA</Badge>
                )}
              </div>
            )}
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-2">
              <FileText className="w-3.5 h-3.5" /> Caixa de Auditoria
            </h3>
            <p className="text-[11px] text-muted-foreground mb-2">
              Observação original extraída do PDF de faturamento
            </p>
            <div className="rounded-lg bg-muted/60 border border-border p-4 text-sm whitespace-pre-wrap font-mono leading-relaxed min-h-[120px]">
              {pedido.observacao_comercial?.trim() ||
                pedido.auditoria?.trim() ||
                "Nenhuma observação registrada para este pedido."}
            </div>
            {pedido.motivo_alocacao && (
              <p className="mt-2 text-xs text-muted-foreground">
                Regras de alocação: {pedido.motivo_alocacao}
              </p>
            )}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground shrink-0">{label}</dt>
      <dd className="text-right font-medium">{value || "—"}</dd>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const liberado = status === "LIBERADO";
  const hub = status === "ENTREGA_TERCEIRO_HUB";
  const retira = status === "RETIRA FOB" || status === "RETIRA_FOB";
  return (
    <span
      className={cn(
        "inline-flex px-2 py-0.5 rounded text-xs font-semibold",
        liberado && "bg-success/15 text-success border border-success/30",
        hub && "bg-primary/15 text-primary border border-primary/30",
        retira && "bg-warning/15 text-warning-foreground border border-warning/40",
        !liberado && !hub && !retira && "bg-destructive/10 text-destructive border border-destructive/30",
      )}
    >
      {status || "—"}
    </span>
  );
}
