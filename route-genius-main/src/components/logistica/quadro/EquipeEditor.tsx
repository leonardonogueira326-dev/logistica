import { useEffect, useState } from "react";

import { type EquipeVeiculo } from "@/lib/logistica-types";

/** Motorista / ajudante / placa do caminhão no dia — salva quando o foco sai do grupo. */
export function EquipeEditor({
  equipe,
  onSalvar,
}: {
  equipe?: EquipeVeiculo;
  onSalvar: (e: EquipeVeiculo) => Promise<void>;
}) {
  const vazio = { motorista: "", ajudante: "", placa: "" };
  const [valor, setValor] = useState<EquipeVeiculo>({ ...vazio, ...(equipe ?? {}) });
  const [editando, setEditando] = useState(false);
  // Atualiza com o servidor só quando ninguém está digitando (senão apagaria o que foi digitado)
  useEffect(() => {
    if (!editando) setValor({ ...vazio, ...(equipe ?? {}) });
  }, [equipe?.motorista, equipe?.ajudante, equipe?.placa, editando]); // eslint-disable-line react-hooks/exhaustive-deps
  const salvar = () => {
    setEditando(false);
    const atual = { ...vazio, ...(equipe ?? {}) };
    if (
      valor.motorista !== atual.motorista ||
      valor.ajudante !== atual.ajudante ||
      valor.placa !== atual.placa
    ) {
      void onSalvar(valor);
    }
  };
  const campo = (k: keyof EquipeVeiculo, rotulo: string) => (
    <input
      className="w-full rounded border border-input bg-background px-1.5 py-0.5 text-[11px] uppercase"
      placeholder={rotulo}
      title={rotulo}
      list={
        k === "motorista"
          ? "lista-motoristas"
          : k === "ajudante"
            ? "lista-ajudantes"
            : "lista-placas"
      }
      value={valor[k]}
      onFocus={() => setEditando(true)}
      onChange={(e) => setValor((v) => ({ ...v, [k]: e.target.value }))}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
  return (
    <div
      className="mt-2 grid grid-cols-[1fr_1fr_72px] gap-1"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) salvar();
      }}
    >
      {campo("motorista", "Motorista")}
      {campo("ajudante", "Ajudante")}
      {campo("placa", "Placa")}
    </div>
  );
}
