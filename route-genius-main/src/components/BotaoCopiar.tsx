import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { copiarTexto } from "@/lib/mensagens";
import { cn } from "@/lib/utils";

export function BotaoCopiar({
  texto,
  rotulo,
  disabled,
  pequeno,
}: {
  texto: string;
  rotulo: string;
  disabled?: boolean;
  pequeno?: boolean;
}) {
  const [ok, setOk] = useState(false);
  return (
    <button
      type="button"
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border bg-background hover:bg-muted disabled:opacity-50",
        pequeno ? "px-2 py-0.5 text-[11px]" : "px-3 py-1.5 text-sm",
      )}
      onClick={async (e) => {
        e.stopPropagation();
        if (await copiarTexto(texto)) {
          setOk(true);
          setTimeout(() => setOk(false), 2000);
        }
      }}
    >
      {ok ? <Check className={pequeno ? "w-3 h-3" : "w-4 h-4"} /> : <Copy className={pequeno ? "w-3 h-3" : "w-4 h-4"} />}
      {ok ? "Copiado!" : rotulo}
    </button>
  );
}
