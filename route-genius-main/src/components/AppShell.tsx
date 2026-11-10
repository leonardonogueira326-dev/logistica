import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getStoredSessionId, setStoredSessionId } from "@/hooks/useLogisticaSession";
import { Link, useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";
import {
  LayoutDashboard,
  Settings2,
  Upload,
  ClipboardCheck,
  TruckIcon,
  Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import { HistoricoSearch } from "@/components/HistoricoSearch";

const navItems = [
  { to: "/", label: "Resumo Executivo", icon: LayoutDashboard },
  { to: "/setup", label: "Mesa de Comando", icon: Settings2 },
  { to: "/upload", label: "Upload & Processamento", icon: Upload },
  { to: "/pendencias", label: "Pendências", icon: ClipboardCheck },
  { to: "/roteirizar", label: "Roteirizar", icon: TruckIcon },
] as const;

/** Status REAL da IA local (Ollama), consultado na API a cada minuto. */
function StatusIA() {
  const { data } = useQuery({
    queryKey: ["ia-status"],
    queryFn: async () => {
      const r = await fetch("/api/ia/status");
      return (await r.json()) as { online: boolean; modelo: string; mensagem: string };
    },
    refetchInterval: 60_000,
    retry: false,
  });
  const online = !!data?.online;
  return (
    <div
      title={data?.mensagem ?? "Verificando IA local…"}
      className={cn(
        "flex items-center gap-2 px-3 py-1.5 rounded-md border text-xs font-medium",
        online ? "bg-success/10 border-success/30 text-success" : "bg-muted border-border text-muted-foreground",
      )}
    >
      <span className={cn("inline-flex rounded-full h-2 w-2", online ? "bg-success" : "bg-muted-foreground/50")} />
      {data ? (online ? "IA local: ativa" : "IA local: desligada") : "IA local…"}
    </div>
  );
}

/** Código na pasta foi atualizado mas o servidor antigo continua rodando. */
function AvisoVersao() {
  const { data } = useQuery({
    queryKey: ["versao"],
    queryFn: async () => {
      const r = await fetch("/api/versao");
      return (await r.json()) as { rodando: string; no_disco: string; desatualizado: boolean };
    },
    refetchInterval: 60_000,
    retry: false,
  });
  if (!data?.desatualizado) return null;
  return (
    <div className="border-b border-amber-500/40 bg-amber-500/15 px-6 py-2 text-sm text-amber-900">
      <b>Tem uma versão nova do sistema.</b> Feche a janela preta e abra o <b>iniciar.bat</b> de novo (depois
      Ctrl+F5) — até lá você está usando a versão antiga.
    </div>
  );
}

type Quadro = {
  session_id: string;
  data_referencia: string;
  solicitacoes: string[];
  linhas: number;
  conferido: boolean;
  quadro_montado: boolean;
};

function dataBR(iso: string) {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso || "sem data";
}

/**
 * Quadro do dia aberto neste PC. Os quadros ficam no SERVIDOR: qualquer PC
 * escolhe aqui e vê o mesmo quadro. Sem quadro escolhido, abre o mais recente.
 */
function QuadroDoDia() {
  const { data: quadros } = useQuery({
    queryKey: ["quadros"],
    queryFn: async () => {
      const r = await fetch("/api/sessions?limite=15");
      return (await r.json()) as Quadro[];
    },
    refetchInterval: 60_000,
  });
  const atual = getStoredSessionId();
  useEffect(() => {
    // Quadro guardado neste navegador não existe mais no servidor (ex.: sistema limpo)
    if (atual && quadros && !quadros.some((x) => x.session_id === atual)) {
      localStorage.removeItem("sf_logistica_session_id");
      if (quadros.length) setStoredSessionId(quadros[0].session_id);
      window.location.reload();
      return;
    }
    if (!atual && quadros && quadros.length) {
      setStoredSessionId(quadros[0].session_id);
      window.location.reload();
    }
  }, [atual, quadros]);
  const abrir = (id: string) => {
    setStoredSessionId(id);
    window.location.reload();
  };
  const q = quadros?.find((x) => x.session_id === atual);
  const rotulo = (x: Quadro) =>
    `${dataBR(x.data_referencia)}${x.solicitacoes.length ? ` · sol. ${x.solicitacoes.map((s) => s.replace(/^0+/, "")).join(", ")}` : ""}`;
  return (
    <select
      className="h-8 max-w-[300px] rounded-md border border-border bg-card px-2 text-xs"
      title="Quadro do dia (fica no servidor — outro PC pode abrir o mesmo)"
      value={atual ?? ""}
      onChange={(e) => e.target.value && abrir(e.target.value)}
    >
      {!q && <option value="">{quadros?.length ? "Escolher quadro do dia…" : "Nenhum quadro ainda"}</option>}
      {(quadros ?? []).map((x) => (
        <option key={x.session_id} value={x.session_id}>
          Quadro {rotulo(x)} · {x.linhas} linhas{x.quadro_montado ? "" : " · não montado"}
        </option>
      ))}
    </select>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  // A página-base do modo servidor é pré-gerada em "/": depois de abrir, o menu
  // é redesenhado (key) para marcar a tela certa.
  const [montado, setMontado] = useState(false);
  useEffect(() => setMontado(true), []);

  return (
    <div className="flex min-h-screen w-full bg-background text-foreground">
      <aside className="hidden md:flex w-64 flex-col bg-sidebar text-sidebar-foreground border-r border-sidebar-border">
        <div className="px-6 py-5 border-b border-sidebar-border">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-lg bg-sidebar-primary flex items-center justify-center">
              <Radio className="w-5 h-5 text-sidebar-primary-foreground" />
            </div>
            <div>
              <div className="font-bold text-sm tracking-tight">SF LOGÍSTICA</div>
              <div className="text-[10px] uppercase tracking-widest text-sidebar-foreground/60">
                Roteirização IA
              </div>
            </div>
          </div>
        </div>
        <nav key={montado ? pathname : "pre"} className="flex-1 px-3 py-4 space-y-1">
          <div className="px-3 pb-2 text-[10px] uppercase tracking-widest text-sidebar-foreground/50">
            Operação
          </div>
          {navItems.map((item) => {
            const active = pathname === item.to;
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors",
                  active
                    ? "bg-sidebar-primary text-sidebar-primary-foreground font-medium"
                    : "text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                )}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="px-4 py-4 border-t border-sidebar-border text-xs">
          <div className="font-semibold">Superfine Steel</div>
          <div className="text-sidebar-foreground/60">Logística · expedição</div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <AvisoVersao />
        <header className="h-16 border-b border-border bg-card flex items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <StatusIA />
            <QuadroDoDia />
            <div className="text-xs text-muted-foreground hidden lg:block">
              Operação · {new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" })}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <HistoricoSearch />
          </div>
        </header>
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}