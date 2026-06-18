import { Link, useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";
import {
  LayoutDashboard,
  Settings2,
  Upload,
  ClipboardCheck,
  TruckIcon,
  AlertTriangle,
  PackageCheck,
  Radio,
  Bell,
  Search,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/", label: "Resumo Executivo", icon: LayoutDashboard },
  { to: "/setup", label: "Mesa de Comando", icon: Settings2 },
  { to: "/upload", label: "Upload & Processamento", icon: Upload },
  { to: "/validacao", label: "Quarentena — Validação", icon: ClipboardCheck },
  { to: "/roteirizar", label: "Pronto p/ Roteirizar", icon: TruckIcon },
  { to: "/bloqueados", label: "Bloqueados & Pendências", icon: AlertTriangle },
  { to: "/retiras", label: "Retiras (FOB)", icon: PackageCheck },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

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
        <nav className="flex-1 px-3 py-4 space-y-1">
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
        <div className="px-4 py-4 border-t border-sidebar-border">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-sidebar-accent flex items-center justify-center text-xs font-bold">
              RC
            </div>
            <div className="text-xs">
              <div className="font-semibold">Rafael Coordenador</div>
              <div className="text-sidebar-foreground/60">Logística · SF</div>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 border-b border-border bg-card flex items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-success/10 border border-success/30">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-success" />
              </span>
              <span className="text-xs font-medium text-success">Motor IA: Online</span>
            </div>
            <div className="text-xs text-muted-foreground hidden lg:block">
              Operação · {new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" })}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="relative hidden md:block">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                placeholder="Buscar pedido, cliente, NF..."
                className="pl-9 pr-3 py-2 text-sm rounded-md border border-input bg-background w-72 outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <button className="relative p-2 rounded-md hover:bg-muted">
              <Bell className="w-4 h-4" />
              <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-destructive" />
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}