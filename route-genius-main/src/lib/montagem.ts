/** Regras da tela de Montagem de Cargas: paradas, checklist "pronto para sair", busca. */
import type { EquipeVeiculo, ItemRota, PainelVeiculo, RotaVeiculo } from "@/lib/logistica-types";
import { idCarga, TEO_ALERTA_MIN } from "@/lib/logistica-types";

/** Mesma paleta do mapa: o caminhão tem a mesma cor no Kanban e no mapa. */
export const CORES_CAMINHAO = [
  "#2563eb",
  "#dc2626",
  "#16a34a",
  "#9333ea",
  "#ea580c",
  "#0891b2",
  "#ca8a04",
  "#be185d",
];
export const corDoCaminhao = (indice: number) => CORES_CAMINHAO[indice % CORES_CAMINHAO.length];

type Linha = ItemRota | Record<string, string>;
const txt = (l: Linha, k: string) => String((l as Record<string, unknown>)[k] ?? "");

export const idDaCarga = (l: Linha) =>
  idCarga(l as { id_carga?: string; id_item?: string; numero_pedido?: string });

/** "MJ ACESSORIOS ... (MJACESSORIOS)" -> "MJACESSORIOS"; sem apelido, o nome sem LTDA/ME. */
export function apelido(nome: string): string {
  const m = /\(([^()]+)\)\s*$/.exec(nome || "");
  if (m) return m[1].trim();
  return (nome || "")
    .replace(/\b(LTDA|EIRELI|ME|EPP|S\/?A)\b\.?/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Mesma chave da otimização no servidor: cliente + cidade. */
export const chaveParada = (l: Linha) =>
  `${txt(l, "cliente_codigo")}|${txt(l, "cidade_destino")}`.toUpperCase();

export interface Parada {
  chave: string;
  numero: number;
  linhas: Linha[];
  ids: string[];
  peso: number;
  cliente: string;
  apelido: string;
  local: string;
}

/** Agrupa as cargas do caminhão por parada, na ordem de entrega (1ª parada = 1ª entrega). */
export function paradas(itens: Linha[]): Parada[] {
  const mapa = new Map<string, Parada>();
  for (const l of itens) {
    const chave = chaveParada(l);
    let p = mapa.get(chave);
    if (!p) {
      const bairro = txt(l, "bairro_destino");
      const cidade = txt(l, "cidade_destino");
      p = {
        chave,
        numero: mapa.size + 1,
        linhas: [],
        ids: [],
        peso: 0,
        cliente: txt(l, "cliente"),
        apelido: apelido(txt(l, "cliente")),
        local: [bairro, cidade].filter(Boolean).join(", "),
      };
      mapa.set(chave, p);
    }
    p.linhas.push(l);
    p.ids.push(idDaCarga(l));
    p.peso += Number((l as Record<string, unknown>).peso_kg ?? 0);
  }
  return [...mapa.values()];
}

export interface ItemChecklist {
  ok: boolean;
  texto: string;
  acao?: "equipe" | "localizar" | "otimizar" | "conferir";
}

/** O que falta para o caminhão sair. Pronto = tudo ok. */
export function checklist(
  rota: RotaVeiculo,
  painel: PainelVeiculo | undefined,
  equipe: EquipeVeiculo | undefined,
  itens: Linha[],
  jornadaMax: number,
): { itens: ItemChecklist[]; pronto: boolean; faltam: number } {
  const teo = parseInt(rota.teo_minutos || rota.tempo_total_min || "0", 10) || 0;
  const semLocal = painel?.sem_localizacao?.length ?? 0;
  const conferir = itens.filter((l) => txt(l, "divisao_automatica") === "SIM").length;
  const lista: ItemChecklist[] = [
    {
      ok: !!equipe?.motorista?.trim() && !!equipe?.placa?.trim(),
      texto:
        equipe?.motorista?.trim() && equipe?.placa?.trim()
          ? "Equipe e placa"
          : "Falta motorista e/ou placa",
      acao: "equipe",
    },
    {
      ok: rota.peso_alocado_kg <= rota.capacidade_kg,
      texto:
        rota.peso_alocado_kg <= rota.capacidade_kg
          ? "Peso dentro da capacidade"
          : `Passou ${(rota.peso_alocado_kg - rota.capacidade_kg).toLocaleString("pt-BR")} kg da capacidade`,
    },
    {
      ok: teo <= Math.min(jornadaMax, TEO_ALERTA_MIN),
      texto:
        teo <= Math.min(jornadaMax, TEO_ALERTA_MIN)
          ? "Jornada dentro do limite"
          : "Jornada acima do limite",
    },
    {
      ok: semLocal === 0,
      texto:
        semLocal === 0
          ? "Todas as paradas no mapa"
          : `${semLocal} carga(s) sem localização no mapa`,
      acao: "localizar",
    },
    {
      ok: !!painel?.ordem_otimizada,
      texto: painel?.ordem_otimizada
        ? "Ordem de entrega otimizada"
        : "Ordem de entrega não otimizada",
      acao: "otimizar",
    },
    {
      ok: conferir === 0,
      texto:
        conferir === 0
          ? "Divisões conferidas"
          : `${conferir} divisão(ões) automática(s) para conferir`,
      acao: "conferir",
    },
  ];
  const faltam = lista.filter((i) => !i.ok).length;
  return { itens: lista, pronto: itens.length > 0 && faltam === 0, faltam };
}

/** Texto onde a busca procura (cliente, apelido, pedido, OF, cidade, bairro, representante). */
export function textoBusca(l: Linha): string {
  return [
    "cliente",
    "numero_pedido",
    "of_ano",
    "cidade_destino",
    "bairro_destino",
    "representante",
    "entrega_em",
  ]
    .map((k) => txt(l, k))
    .join(" ")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toUpperCase();
}

export function casaBusca(l: Linha, termo: string): boolean {
  const t = termo.trim().normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
  if (!t) return false;
  const alvo = textoBusca(l);
  return t.split(/\s+/).every((p) => alvo.includes(p));
}
