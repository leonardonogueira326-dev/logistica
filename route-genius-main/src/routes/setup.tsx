import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Clock, Gauge, PackageOpen, Truck, Settings2 } from "lucide-react";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/setup")({
  head: () => ({ meta: [{ title: "Mesa de Comando · Setup" }] }),
  component: SetupPage,
});

interface Caminhao {
  id: string;
  modelo: string;
  carroceria: string;
  capacidade: string;
  pisos: number;
  reserva?: boolean;
  ativo: boolean;
}

const frotaInicial: Caminhao[] = [
  { id: "T1", modelo: "11.180", carroceria: "Baú", capacidade: "6.000 kg", pisos: 16, ativo: true },
  { id: "T2", modelo: "11.180", carroceria: "Spyder", capacidade: "5.700 kg", pisos: 12, ativo: true },
  { id: "T3", modelo: "10.160", carroceria: "Spyder", capacidade: "4.700 kg", pisos: 10, ativo: true },
  { id: "T4", modelo: "Van Master", carroceria: "Furgão", capacidade: "1.800 kg", pisos: 6, reserva: true, ativo: false },
];

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={cn(
        "relative w-11 h-6 rounded-full transition-colors",
        checked ? "bg-success" : "bg-muted-foreground/30",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform",
          checked && "translate-x-5",
        )}
      />
    </button>
  );
}

function Section({ icon: Icon, title, desc, children }: { icon: typeof Settings2; title: string; desc: string; children: React.ReactNode }) {
  return (
    <section className="bg-card rounded-xl border border-border shadow-sm">
      <div className="flex items-center gap-3 px-5 py-4 border-b border-border">
        <div className="w-9 h-9 rounded-md bg-primary/10 text-primary flex items-center justify-center">
          <Icon className="w-4 h-4" />
        </div>
        <div>
          <h2 className="font-semibold">{title}</h2>
          <p className="text-xs text-muted-foreground">{desc}</p>
        </div>
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Field({ label, children, suffix }: { label: string; children: React.ReactNode; suffix?: string }) {
  return (
    <label className="block">
      <div className="text-xs font-medium text-muted-foreground mb-1.5">{label}</div>
      <div className="relative">
        {children}
        {suffix && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">{suffix}</span>
        )}
      </div>
    </label>
  );
}

const inputCls = "w-full px-3 py-2 text-sm rounded-md border border-input bg-background outline-none focus:ring-2 focus:ring-ring";

function SetupPage() {
  const [spyderBau, setSpyderBau] = useState(true);
  const [frota, setFrota] = useState(frotaInicial);

  return (
    <div className="p-6 space-y-6 max-w-6xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Mesa de Comando</h1>
        <p className="text-sm text-muted-foreground">Calibre a operação do dia antes de gerar as rotas.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Section icon={Clock} title="Parâmetros da Operação" desc="Janela de tempo e produtividade padrão.">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Horário de Início"><input className={inputCls} defaultValue="07:00" /></Field>
            <Field label="Horário Limite de Retorno"><input className={inputCls} defaultValue="17:00" /></Field>
            <Field label="Tempo de Descarga / Cliente" suffix="min"><input className={inputCls} defaultValue="20" /></Field>
            <Field label="Velocidade Média" suffix="km/h"><input className={inputCls} defaultValue="42" /></Field>
          </div>
        </Section>

        <Section icon={PackageOpen} title="Acondicionamento Spyder" desc="Regras para coexistência de Spyder no Baú.">
          <div className="space-y-4">
            <div className="flex items-center justify-between p-3 rounded-md bg-muted/40">
              <div>
                <div className="text-sm font-medium">Permitir Spyder no Baú</div>
                <div className="text-xs text-muted-foreground">Quando ativo, o motor pode mesclar cargas Spyder em Baú livre.</div>
              </div>
              <Toggle checked={spyderBau} onChange={setSpyderBau} />
            </div>
            <Field label="Peso Máximo do Spyder no Baú" suffix="kg">
              <input className={inputCls} defaultValue="800" disabled={!spyderBau} />
            </Field>
            <Field label="Vagas Máx. Piso para Spyder Combinado">
              <input className={inputCls} defaultValue="4" disabled={!spyderBau} />
            </Field>
          </div>
        </Section>
      </div>

      <Section icon={Truck} title="Gestão de Frota" desc="Selecione os veículos disponíveis para a operação de hoje.">
        <div className="overflow-x-auto -mx-5">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground bg-muted/40">
                <th className="px-5 py-2">Veículo</th>
                <th className="py-2">Carroceria</th>
                <th className="py-2">Capacidade</th>
                <th className="py-2">Pisos</th>
                <th className="py-2">Tipo</th>
                <th className="py-2 text-right pr-5">Disponível</th>
              </tr>
            </thead>
            <tbody>
              {frota.map((c) => (
                <tr key={c.id} className="border-t border-border hover:bg-muted/30">
                  <td className="px-5 py-3 font-semibold">{c.modelo}</td>
                  <td className="py-3">{c.carroceria}</td>
                  <td className="py-3 font-mono">{c.capacidade}</td>
                  <td className="py-3">{c.pisos}</td>
                  <td className="py-3">
                    {c.reserva ? (
                      <span className="px-2 py-0.5 text-[11px] rounded bg-warning/20 text-warning-foreground border border-warning/40">Reserva</span>
                    ) : (
                      <span className="px-2 py-0.5 text-[11px] rounded bg-success/15 text-success border border-success/30">Titular</span>
                    )}
                  </td>
                  <td className="py-3 pr-5">
                    <div className="flex justify-end">
                      <Toggle checked={c.ativo} onChange={(v) => setFrota((f) => f.map((x) => x.id === c.id ? { ...x, ativo: v } : x))} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="flex justify-end gap-2">
        <button className="px-4 py-2 text-sm rounded-md border border-border bg-card hover:bg-muted">Restaurar Padrões</button>
        <button className="px-5 py-2 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:opacity-90">
          <Gauge className="w-4 h-4 inline mr-1.5" />
          Salvar Calibração
        </button>
      </div>
    </div>
  );
}