import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useRef, useState } from "react";
import {
  CheckCircle2,
  FileSpreadsheet,
  FileText,
  Loader2,
  Mail,
  UploadCloud,
  Zap,
} from "lucide-react";

import {
  setStoredSessionId,
  useLogisticaSession,
} from "@/hooks/useLogisticaSession";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/upload")({
  head: () => ({ meta: [{ title: "Upload & Processamento" }] }),
  component: UploadPage,
});

type SlotId = "pdf" | "xlsb" | "msg";

const slots: {
  id: SlotId;
  label: string;
  icon: typeof FileText;
  accept: string;
}[] = [
  { id: "pdf", label: "PDF de Faturamento", icon: FileText, accept: ".pdf" },
  { id: "xlsb", label: "Relatório NFPARADA (.xlsb)", icon: FileSpreadsheet, accept: ".xlsb,.xlsx" },
  { id: "msg", label: "E-mail do Comercial (.msg)", icon: Mail, accept: ".msg" },
];

function UploadPage() {
  const navigate = useNavigate();
  const { uploadMutation, ingestMutation } = useLogisticaSession(null);
  const [files, setFiles] = useState<Partial<Record<SlotId, File>>>({});
  const [step, setStep] = useState<"idle" | "upload" | "ingest" | "done" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const inputRefs = useRef<Partial<Record<SlotId, HTMLInputElement | null>>>({});

  const hasPdf = !!files.pdf;
  const canRun = hasPdf;

  const pickFile = (id: SlotId, file: File | undefined) => {
    if (!file) return;
    setFiles((prev) => ({ ...prev, [id]: file }));
  };

  const run = async () => {
    if (!canRun) return;
    setStep("upload");
    setErrorMsg("");
    try {
      const result = await uploadMutation.mutateAsync({
        pdf: files.pdf,
        xlsb: files.xlsb,
        msg: files.msg,
      });
      setStoredSessionId(result.session_id);
      setStep("ingest");
      await ingestMutation.mutateAsync(result.session_id);
      setStep("done");
      setTimeout(() => navigate({ to: "/validacao" }), 600);
    } catch (err) {
      setStep("error");
      setErrorMsg(err instanceof Error ? err.message : "Erro no processamento");
    }
  };

  const running = step === "upload" || step === "ingest";

  return (
    <div className="p-6 max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Upload & Cruzamento</h1>
        <p className="text-sm text-muted-foreground">
          Envie as fontes do dia. O motor consolida PDF + NFPARADA + e-mail e abre a quarentena de validação.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {slots.map((s) => {
          const file = files[s.id];
          const Icon = s.icon;
          return (
            <div key={s.id}>
              <input
                ref={(el) => {
                  inputRefs.current[s.id] = el;
                }}
                type="file"
                accept={s.accept}
                className="hidden"
                onChange={(e) => pickFile(s.id, e.target.files?.[0])}
              />
              <button
                type="button"
                onClick={() => inputRefs.current[s.id]?.click()}
                className={cn(
                  "group w-full border-2 border-dashed rounded-xl p-6 text-left transition-all bg-card",
                  file
                    ? "border-success bg-success/5"
                    : "border-border hover:border-accent hover:bg-accent/5",
                )}
              >
                <div className="flex items-center justify-between">
                  <div
                    className={cn(
                      "w-10 h-10 rounded-md flex items-center justify-center",
                      file ? "bg-success/15 text-success" : "bg-muted text-muted-foreground",
                    )}
                  >
                    <Icon className="w-5 h-5" />
                  </div>
                  {file ? (
                    <CheckCircle2 className="w-5 h-5 text-success" />
                  ) : (
                    <UploadCloud className="w-5 h-5 text-muted-foreground group-hover:text-accent" />
                  )}
                </div>
                <div className="mt-4 font-semibold text-sm">{s.label}</div>
                {file ? (
                  <div className="mt-1 text-xs text-success font-mono truncate">
                    {file.name} · {(file.size / 1024).toFixed(0)} KB
                  </div>
                ) : (
                  <div className="mt-1 text-xs text-muted-foreground">
                    {s.id === "pdf" ? "Obrigatório" : "Opcional"} — clique para selecionar
                  </div>
                )}
              </button>
            </div>
          );
        })}
      </div>

      <div className="bg-card border border-border rounded-xl p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold">Motor de Ingestão Superfine</div>
            <div className="text-xs text-muted-foreground">
              PDF + XLSB + MSG · enriquecimento cadastro mestre · API Fase 3
            </div>
          </div>
          <button
            disabled={!canRun || running}
            onClick={run}
            className={cn(
              "inline-flex items-center gap-2 px-5 py-3 rounded-md font-semibold text-sm shadow-sm transition-all",
              !canRun || running
                ? "bg-muted text-muted-foreground cursor-not-allowed"
                : "bg-accent text-accent-foreground hover:opacity-90 hover:shadow-lg",
            )}
          >
            {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            Executar ingestão
          </button>
        </div>

        {running && (
          <div className="mt-6 space-y-2 text-sm text-muted-foreground">
            <div className="flex items-center gap-2">
              {step === "upload" ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <CheckCircle2 className="w-4 h-4 text-success" />
              )}
              Enviando arquivos…
            </div>
            <div className="flex items-center gap-2">
              {step === "ingest" ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <span className="w-4 h-4 rounded-full bg-muted" />
              )}
              Consolidando e enriquecendo pedidos…
            </div>
          </div>
        )}

        {step === "done" && (
          <div className="mt-4 p-4 rounded-md bg-success/10 border border-success/30 text-sm">
            Ingestão concluída. Redirecionando para validação…
          </div>
        )}

        {step === "error" && (
          <div className="mt-4 p-4 rounded-md bg-destructive/10 border border-destructive/30 text-sm">
            {errorMsg}
          </div>
        )}
      </div>
    </div>
  );
}
