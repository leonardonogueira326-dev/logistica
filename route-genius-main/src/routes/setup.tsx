import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import {
  CalendarClock,
  Clock,
  Loader2,
  MapPin,
  Plus,
  Save,
  Trash2,
  Truck,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getConfig, saveConfig } from "@/lib/api-client";
import type { ConfiguracaoOperacional, PessoaEquipe, RotaSetup, VeiculoSetup } from "@/lib/logistica-types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/setup")({
  head: () => ({ meta: [{ title: "Mesa de Comando · Setup" }] }),
  component: SetupPage,
});

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
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

const inputCls =
  "w-full px-3 py-2 text-sm rounded-md border border-input bg-background outline-none focus:ring-2 focus:ring-ring";

function formatTempoHoras(minutos: number): string {
  if (!minutos || minutos <= 0) return "—";
  const h = Math.floor(minutos / 60);
  const m = minutos % 60;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}min`;
}

function SaveBar({
  label,
  saving,
  onSave,
}: {
  label: string;
  saving: boolean;
  onSave: () => void;
}) {
  return (
    <div className="flex justify-end pt-4 border-t border-border mt-4">
      <button
        type="button"
        disabled={saving}
        onClick={onSave}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
      >
        {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
        {label}
      </button>
    </div>
  );
}

function SetupPage() {
  const [config, setConfig] = useState<ConfiguracaoOperacional | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingTab, setSavingTab] = useState<string | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const resp = await getConfig();
      setConfig(resp.config);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Falha ao carregar configuração.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = (partial: Partial<ConfiguracaoOperacional>) => {
    setConfig((c) => (c ? { ...c, ...partial } : c));
  };

  const salvar = async (tab: string) => {
    if (!config) return;
    setSavingTab(tab);
    setErr("");
    try {
      const resp = await saveConfig(config);
      setConfig(resp.config);
      toast.success(resp.message || "Configuração Atualizada com Sucesso");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Falha ao salvar.";
      setErr(msg);
      toast.error(msg);
    } finally {
      setSavingTab(null);
    }
  };

  const updateVeiculo = (idx: number, field: keyof VeiculoSetup, value: string | number | boolean) => {
    if (!config) return;
    const frota = [...config.frota];
    frota[idx] = { ...frota[idx], [field]: value };
    patch({ frota });
  };

  const addVeiculo = () => {
    if (!config) return;
    const n = config.frota.length + 1;
    const novo: VeiculoSetup = {
      id: `VEICULO_${n}`,
      placa: "",
      nome: "",
      capacidade_kg: 6000,
      tipo: "BAU",
      ativo: false,
      reserva: false,
    };
    patch({ frota: [...config.frota, novo] });
  };

  const removeVeiculo = (idx: number) => {
    if (!config) return;
    patch({ frota: config.frota.filter((_, i) => i !== idx) });
  };

  const updateRota = (idx: number, field: keyof RotaSetup, value: string | number) => {
    if (!config) return;
    const rotas = [...config.rotas];
    rotas[idx] = { ...rotas[idx], [field]: value };
    patch({ rotas });
  };

  const addRota = () => {
    if (!config) return;
    patch({
      rotas: [
        ...config.rotas,
        {
          cidade: "",
          rota_logistica: "ROTA_OUTROS",
          macro_regiao: "OUTROS",
          tempo_medio_viagem_min: 120,
        },
      ],
    });
  };

  const removeRota = (idx: number) => {
    if (!config) return;
    patch({ rotas: config.rotas.filter((_, i) => i !== idx) });
  };

  const addPessoa = (tipo: "motoristas" | "ajudantes") => {
    if (!config) return;
    const pessoa: PessoaEquipe = { nome: "Novo", cnh: "", telefone: "" };
    patch({
      equipe: {
        ...config.equipe,
        [tipo]: [...config.equipe[tipo], pessoa],
      },
    });
  };

  const updatePessoa = (tipo: "motoristas" | "ajudantes", idx: number, field: keyof PessoaEquipe, value: string) => {
    if (!config) return;
    const lista = [...config.equipe[tipo]];
    lista[idx] = { ...lista[idx], [field]: value };
    patch({ equipe: { ...config.equipe, [tipo]: lista } });
  };

  const removePessoa = (tipo: "motoristas" | "ajudantes", idx: number) => {
    if (!config) return;
    patch({
      equipe: {
        ...config.equipe,
        [tipo]: config.equipe[tipo].filter((_, i) => i !== idx),
      },
    });
  };

  if (loading) {
    return (
      <div className="p-6 flex items-center gap-2 text-muted-foreground">
        <Loader2 className="w-4 h-4 animate-spin" />
        Carregando configuração operacional…
      </div>
    );
  }

  if (!config) {
    return (
      <div className="p-6">
        <p className="text-destructive">{err || "Configuração indisponível."}</p>
        <button type="button" onClick={() => void load()} className="mt-3 px-4 py-2 text-sm rounded-md border">
          Tentar novamente
        </button>
      </div>
    );
  }

  const { horarios, operacao } = config;

  return (
    <div className="p-6 space-y-6 max-w-6xl">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Parametrização Operacional</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Controle total sobre frota, equipe, rotas e calendário — sem editar JSON manualmente.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted"
        >
          Recarregar do servidor
        </button>
      </div>

      {err && (
        <div className="text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-md px-4 py-2">
          {err}
        </div>
      )}

      <Tabs defaultValue="frota" className="w-full">
        <TabsList className="flex flex-wrap h-auto gap-1 p-1">
          <TabsTrigger value="frota" className="gap-1.5">
            <Truck className="w-3.5 h-3.5" /> Frota
          </TabsTrigger>
          <TabsTrigger value="equipe" className="gap-1.5">
            <Users className="w-3.5 h-3.5" /> Equipe
          </TabsTrigger>
          <TabsTrigger value="rotas" className="gap-1.5">
            <MapPin className="w-3.5 h-3.5" /> Rotas / Cidades
          </TabsTrigger>
          <TabsTrigger value="calendario" className="gap-1.5">
            <CalendarClock className="w-3.5 h-3.5" /> Calendário
          </TabsTrigger>
          <TabsTrigger value="operacao" className="gap-1.5">
            <Clock className="w-3.5 h-3.5" /> Operação
          </TabsTrigger>
        </TabsList>

        <TabsContent value="frota" className="mt-4">
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="font-semibold">Frota</h2>
                <p className="text-xs text-muted-foreground">ID, placa, capacidade (kg) e status ativo/inativo.</p>
              </div>
              <button
                type="button"
                onClick={addVeiculo}
                className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border border-primary text-primary hover:bg-primary/5"
              >
                <Plus className="w-3.5 h-3.5" /> Adicionar caminhão
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground bg-muted/40">
                    <th className="px-3 py-2">ID</th>
                    <th className="py-2">Placa</th>
                    <th className="py-2">Nome</th>
                    <th className="py-2">Capacidade (kg)</th>
                    <th className="py-2">Tipo</th>
                    <th className="py-2 text-center">Ativo</th>
                    <th className="py-2 w-10" />
                  </tr>
                </thead>
                <tbody>
                  {config.frota.length === 0 && (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-muted-foreground text-xs">
                        Nenhum veículo cadastrado.
                      </td>
                    </tr>
                  )}
                  {config.frota.map((v, i) => (
                    <tr key={`${v.id}-${i}`} className="border-t border-border">
                      <td className="px-3 py-2">
                        <input
                          className={cn(inputCls, "font-mono text-xs")}
                          value={v.id}
                          onChange={(e) => updateVeiculo(i, "id", e.target.value)}
                        />
                      </td>
                      <td className="py-2">
                        <input className={inputCls} value={v.placa} onChange={(e) => updateVeiculo(i, "placa", e.target.value)} />
                      </td>
                      <td className="py-2">
                        <input className={inputCls} value={v.nome} onChange={(e) => updateVeiculo(i, "nome", e.target.value)} />
                      </td>
                      <td className="py-2">
                        <input
                          type="number"
                          className={inputCls}
                          value={v.capacidade_kg}
                          onChange={(e) => updateVeiculo(i, "capacidade_kg", Number(e.target.value))}
                        />
                      </td>
                      <td className="py-2">
                        <select
                          className={inputCls}
                          value={v.tipo}
                          onChange={(e) => updateVeiculo(i, "tipo", e.target.value)}
                        >
                          <option value="BAU">BAU</option>
                          <option value="SYDER">SYDER</option>
                        </select>
                      </td>
                      <td className="py-2">
                        <div className="flex justify-center">
                          <Toggle checked={v.ativo} onChange={(val) => updateVeiculo(i, "ativo", val)} />
                        </div>
                      </td>
                      <td className="py-2">
                        <button
                          type="button"
                          onClick={() => removeVeiculo(i)}
                          className="p-1.5 rounded hover:bg-destructive/10 text-destructive"
                          title="Remover"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <SaveBar
              label="Salvar Alterações — Frota"
              saving={savingTab === "frota"}
              onSave={() => void salvar("frota")}
            />
          </div>
        </TabsContent>

        <TabsContent value="equipe" className="mt-4">
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <h2 className="font-semibold mb-1">Equipe</h2>
            <p className="text-xs text-muted-foreground mb-4">Motoristas e ajudantes — nome, CNH e telefone.</p>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              {(["motoristas", "ajudantes"] as const).map((tipo) => (
                <div key={tipo}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-medium capitalize">{tipo}</h3>
                    <button
                      type="button"
                      onClick={() => addPessoa(tipo)}
                      className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                    >
                      <Plus className="w-3 h-3" /> Adicionar
                    </button>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-[11px] uppercase text-muted-foreground">
                          <th className="py-1.5">Nome</th>
                          <th className="py-1.5">CNH</th>
                          <th className="py-1.5">Telefone</th>
                          <th className="w-8" />
                        </tr>
                      </thead>
                      <tbody>
                        {config.equipe[tipo].length === 0 && (
                          <tr>
                            <td colSpan={4} className="py-4 text-xs text-muted-foreground">
                              Nenhum cadastro.
                            </td>
                          </tr>
                        )}
                        {config.equipe[tipo].map((p, i) => (
                          <tr key={`${tipo}-${i}`} className="border-t border-border">
                            <td className="py-1.5 pr-1">
                              <input className={inputCls} value={p.nome} onChange={(e) => updatePessoa(tipo, i, "nome", e.target.value)} />
                            </td>
                            <td className="py-1.5 pr-1">
                              <input className={inputCls} value={p.cnh ?? ""} onChange={(e) => updatePessoa(tipo, i, "cnh", e.target.value)} />
                            </td>
                            <td className="py-1.5 pr-1">
                              <input className={inputCls} value={p.telefone ?? ""} onChange={(e) => updatePessoa(tipo, i, "telefone", e.target.value)} />
                            </td>
                            <td className="py-1.5">
                              <button type="button" onClick={() => removePessoa(tipo, i)} className="p-1 text-destructive hover:bg-destructive/10 rounded">
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
            <SaveBar
              label="Salvar Alterações — Equipe"
              saving={savingTab === "equipe"}
              onSave={() => void salvar("equipe")}
            />
          </div>
        </TabsContent>

        <TabsContent value="rotas" className="mt-4">
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="font-semibold">Rotas / Cidades</h2>
                <p className="text-xs text-muted-foreground">
                  Ex.: Americana → Região Leste → 2h (120 min)
                </p>
              </div>
              <button
                type="button"
                onClick={addRota}
                className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border border-primary text-primary hover:bg-primary/5"
              >
                <Plus className="w-3.5 h-3.5" /> Adicionar cidade
              </button>
            </div>
            <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-muted/40">
                  <tr className="text-left text-[11px] uppercase text-muted-foreground">
                    <th className="px-3 py-2">Cidade</th>
                    <th className="py-2">Rota Logística</th>
                    <th className="py-2">Macro Região</th>
                    <th className="py-2">Tempo (min)</th>
                    <th className="py-2">≈ Horas</th>
                    <th className="w-10" />
                  </tr>
                </thead>
                <tbody>
                  {config.rotas.map((r, i) => (
                    <tr key={`rota-${i}`} className="border-t border-border">
                      <td className="px-3 py-1.5">
                        <input className={inputCls} value={r.cidade} onChange={(e) => updateRota(i, "cidade", e.target.value.toUpperCase())} />
                      </td>
                      <td className="py-1.5">
                        <input className={inputCls} value={r.rota_logistica} onChange={(e) => updateRota(i, "rota_logistica", e.target.value.toUpperCase())} />
                      </td>
                      <td className="py-1.5">
                        <input className={inputCls} value={r.macro_regiao} onChange={(e) => updateRota(i, "macro_regiao", e.target.value)} />
                      </td>
                      <td className="py-1.5">
                        <input
                          type="number"
                          className={inputCls}
                          value={r.tempo_medio_viagem_min}
                          onChange={(e) => updateRota(i, "tempo_medio_viagem_min", Number(e.target.value))}
                        />
                      </td>
                      <td className="py-1.5 text-xs text-muted-foreground whitespace-nowrap">
                        {formatTempoHoras(r.tempo_medio_viagem_min)}
                      </td>
                      <td className="py-1.5">
                        <button type="button" onClick={() => removeRota(i)} className="p-1 text-destructive hover:bg-destructive/10 rounded">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <SaveBar
              label="Salvar Alterações — Rotas"
              saving={savingTab === "rotas"}
              onSave={() => void salvar("rotas")}
            />
          </div>
        </TabsContent>

        <TabsContent value="calendario" className="mt-4">
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <h2 className="font-semibold mb-1">Calendário e Jornada</h2>
            <p className="text-xs text-muted-foreground mb-4">Horários de saída, retorno e parâmetros de jornada.</p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <label className="block text-sm">
                <span className="text-xs font-medium text-muted-foreground">Início Expediente</span>
                <input
                  className={cn(inputCls, "mt-1")}
                  value={horarios.inicio_expediente}
                  onChange={(e) => patch({ horarios: { ...horarios, inicio_expediente: e.target.value } })}
                />
              </label>
              <label className="block text-sm">
                <span className="text-xs font-medium text-muted-foreground">Limite Retorno</span>
                <input
                  className={cn(inputCls, "mt-1")}
                  value={horarios.limite_retorno}
                  onChange={(e) => patch({ horarios: { ...horarios, limite_retorno: e.target.value } })}
                />
              </label>
              <label className="block text-sm">
                <span className="text-xs font-medium text-muted-foreground">Descarga / Cliente (min)</span>
                <input
                  type="number"
                  className={cn(inputCls, "mt-1")}
                  value={horarios.tempo_descarga_minutos}
                  onChange={(e) => patch({ horarios: { ...horarios, tempo_descarga_minutos: Number(e.target.value) } })}
                />
              </label>
              <label className="block text-sm">
                <span className="text-xs font-medium text-muted-foreground">Almoço (min)</span>
                <input
                  type="number"
                  className={cn(inputCls, "mt-1")}
                  value={horarios.tempo_almoco_minutos}
                  onChange={(e) => patch({ horarios: { ...horarios, tempo_almoco_minutos: Number(e.target.value) } })}
                />
              </label>
              <label className="block text-sm">
                <span className="text-xs font-medium text-muted-foreground">Jornada Máxima (min)</span>
                <input
                  type="number"
                  className={cn(inputCls, "mt-1")}
                  value={horarios.jornada_maxima_minutos}
                  onChange={(e) => patch({ horarios: { ...horarios, jornada_maxima_minutos: Number(e.target.value) } })}
                />
              </label>
              <label className="block text-sm">
                <span className="text-xs font-medium text-muted-foreground">Velocidade Média (km/h)</span>
                <input
                  type="number"
                  className={cn(inputCls, "mt-1")}
                  value={horarios.velocidade_media_kmh}
                  onChange={(e) => patch({ horarios: { ...horarios, velocidade_media_kmh: Number(e.target.value) } })}
                />
              </label>
            </div>
            <SaveBar
              label="Salvar Alterações — Calendário"
              saving={savingTab === "calendario"}
              onSave={() => void salvar("calendario")}
            />
          </div>
        </TabsContent>

        <TabsContent value="operacao" className="mt-4">
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <h2 className="font-semibold mb-1">Parâmetros de Operação</h2>
            <p className="text-xs text-muted-foreground mb-4">Spyder no baú e regras complementares.</p>
            <div className="space-y-4 max-w-lg">
              <div className="flex items-center justify-between p-3 rounded-md bg-muted/40">
                <div>
                  <div className="text-sm font-medium">Permitir Spyder no Baú</div>
                  <div className="text-xs text-muted-foreground">Mesclar cargas Spyder em baú livre.</div>
                </div>
                <Toggle
                  checked={operacao.permitir_spyder_no_bau}
                  onChange={(v) => patch({ operacao: { ...operacao, permitir_spyder_no_bau: v } })}
                />
              </div>
              <label className="block text-sm">
                <span className="text-xs font-medium text-muted-foreground">Peso máx. Spyder no baú (kg)</span>
                <input
                  type="number"
                  className={cn(inputCls, "mt-1")}
                  value={operacao.peso_max_spyder_no_bau_kg}
                  disabled={!operacao.permitir_spyder_no_bau}
                  onChange={(e) => patch({ operacao: { ...operacao, peso_max_spyder_no_bau_kg: Number(e.target.value) } })}
                />
              </label>
            </div>
            <SaveBar
              label="Salvar Alterações — Operação"
              saving={savingTab === "operacao"}
              onSave={() => void salvar("operacao")}
            />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
