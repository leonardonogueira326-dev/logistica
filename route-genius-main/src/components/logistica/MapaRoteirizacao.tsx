import L from "leaflet";
import { useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";

import type { ItemRota, PedidoConsolidado, Roteirizacao } from "@/lib/logistica-types";
import { CORES_CAMINHAO, chaveParada } from "@/lib/montagem";

import "leaflet/dist/leaflet.css";

import iconRetina from "leaflet/dist/images/marker-icon-2x.png";
import icon from "leaflet/dist/images/marker-icon.png";
import iconShadow from "leaflet/dist/images/marker-shadow.png";

const BASE_AMERICANA: [number, number] = [-22.739, -47.331];

const COR_BACKLOG = "rgba(100, 100, 100, 0.72)";

delete (L.Icon.Default.prototype as unknown as { _getIconUrl?: unknown })._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: iconRetina,
  iconUrl: icon,
  shadowUrl: iconShadow,
});

type PontoMapa = {
  key: string;
  idItem: string;
  lat: number;
  lng: number;
  numeroPedido: string;
  cliente: string;
  peso: number;
  cor: string;
  caminhao?: string;
  /** Nº da parada no caminhão (o mesmo do quadro) */
  numero?: number;
};

type RotaCaminhao = {
  veiculoId: string;
  veiculoNome: string;
  cor: string;
  pontos: [number, number][];
  marcadores: PontoMapa[];
};

function criarIconeCor(cor: string, numero?: number) {
  if (numero !== undefined) {
    return L.divIcon({
      className: "mapa-rota-marker",
      html: `<div style="background:${cor};min-width:22px;height:22px;padding:0 4px;border-radius:11px;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.4);color:#fff;font:700 11px/18px system-ui,sans-serif;text-align:center">${numero}</div>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    });
  }
  return L.divIcon({
    className: "mapa-rota-marker",
    html: `<div style="background:${cor};width:16px;height:16px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.35)"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function coordsDoPedido(
  numeroPedido: string,
  fallbackCliente: string,
  fallbackPeso: number,
  consolidadosByPedido: Record<string, PedidoConsolidado>,
): { lat: number; lng: number; cliente: string; peso: number } | null {
  const cons = consolidadosByPedido[numeroPedido];
  if (!cons?.latitude || !cons?.longitude) return null;
  return {
    lat: cons.latitude,
    lng: cons.longitude,
    cliente: cons.cliente || fallbackCliente,
    peso: cons.peso_kg ?? fallbackPeso,
  };
}

function itemParaPonto(
  item: ItemRota,
  cor: string,
  consolidadosByPedido: Record<string, PedidoConsolidado>,
  caminhao?: string,
): PontoMapa | null {
  const coords = coordsDoPedido(
    item.id_item || item.numero_pedido,
    item.cliente,
    item.peso_kg,
    consolidadosByPedido,
  );
  if (!coords) return null;
  return {
    key: `${caminhao ?? "pool"}-${item.id_carga || item.numero_pedido}`,
    idItem: item.id_item || item.numero_pedido,
    lat: coords.lat,
    lng: coords.lng,
    numeroPedido: item.numero_pedido,
    cliente: coords.cliente,
    peso: coords.peso,
    cor,
    caminhao,
  };
}

function backlogParaPonto(
  entry: Record<string, string>,
  poolKey: string,
  consolidadosByPedido: Record<string, PedidoConsolidado>,
): PontoMapa | null {
  const numeroPedido = entry.id_item || entry.numero_pedido || "";
  if (!numeroPedido) return null;
  const coords = coordsDoPedido(
    numeroPedido,
    entry.cliente ?? "",
    parseFloat(entry.peso_kg ?? "0") || 0,
    consolidadosByPedido,
  );
  if (!coords) return null;
  return {
    idItem: entry.id_item || entry.numero_pedido || "",
    key: `${poolKey}-${numeroPedido}`,
    lat: coords.lat,
    lng: coords.lng,
    numeroPedido,
    cliente: coords.cliente,
    peso: coords.peso,
    cor: COR_BACKLOG,
  };
}

function FitBoundsOnMarkers({ bounds }: { bounds: L.LatLngBounds | null }) {
  const map = useMap();
  useEffect(() => {
    if (bounds?.isValid()) {
      map.fitBounds(bounds, { padding: [48, 48], maxZoom: 13 });
    }
  }, [bounds, map]);
  return null;
}

function MapaRoteirizacaoInner({
  data,
  consolidadosByPedido,
  onCorrigir,
  compacto,
}: {
  data: Roteirizacao;
  consolidadosByPedido: Record<string, PedidoConsolidado>;
  onCorrigir?: (idItem: string, lat: number, lng: number) => void;
  compacto?: boolean;
}) {
  const { rotasCaminhao, pontosBacklog, bounds, semCoordenadas } = useMemo(() => {
    const rotas: RotaCaminhao[] = data.rotas.map((rota, idx) => {
      const cor = CORES_CAMINHAO[idx % CORES_CAMINHAO.length];
      const itens = data.itens_por_veiculo[rota.veiculo_id] ?? [];
      const retorno = data.itens_retorno_por_veiculo[rota.veiculo_id] ?? [];
      const todosItens = [...itens, ...retorno];

      const marcadores: PontoMapa[] = [];
      const pontos: [number, number][] = [];
      const nome = data.painel_veiculos?.[rota.veiculo_id]?.nome ?? rota.veiculo_nome;
      const numeroDa: Record<string, number> = {};
      for (const item of itens) {
        const k = chaveParada(item);
        if (!(k in numeroDa)) numeroDa[k] = Object.keys(numeroDa).length + 1;
      }
      const jaMarcado = new Set<string>();
      for (const item of todosItens) {
        const ponto = itemParaPonto(item, cor, consolidadosByPedido, nome);
        if (!ponto) continue;
        const k = chaveParada(item);
        pontos.push([ponto.lat, ponto.lng]);
        if (jaMarcado.has(k)) continue; // um marcador por parada
        jaMarcado.add(k);
        marcadores.push({ ...ponto, numero: numeroDa[k] });
      }

      return {
        veiculoId: rota.veiculo_id,
        veiculoNome: nome,
        cor,
        pontos,
        marcadores,
      };
    });

    const backlogEntries = [
      ...data.backlog.map((b) => ({ entry: b, pool: "backlog" as const })),
      ...(data.backlog_futuro ?? []).map((b) => ({ entry: b, pool: "futuro" as const })),
      ...(data.backlog_local ?? []).map((b) => ({ entry: b, pool: "local" as const })),
    ];

    const pool: PontoMapa[] = [];
    let missing = 0;

    for (const { entry, pool: poolKey } of backlogEntries) {
      const ponto = backlogParaPonto(entry, poolKey, consolidadosByPedido);
      if (ponto) pool.push(ponto);
      else if (entry.numero_pedido) missing += 1;
    }

    for (const rota of rotas) {
      const itens = [
        ...(data.itens_por_veiculo[rota.veiculoId] ?? []),
        ...(data.itens_retorno_por_veiculo[rota.veiculoId] ?? []),
      ];
      for (const item of itens) {
        if (
          !coordsDoPedido(
            item.id_item || item.numero_pedido,
            item.cliente,
            item.peso_kg,
            consolidadosByPedido,
          )
        ) {
          missing += 1;
        }
      }
    }

    const allCoords: [number, number][] = [
      ...rotas.flatMap((r) => r.pontos),
      ...pool.map((p) => [p.lat, p.lng] as [number, number]),
    ];

    let boundsCalc: L.LatLngBounds | null = null;
    if (allCoords.length > 0) {
      boundsCalc = L.latLngBounds(allCoords);
    }

    return {
      rotasCaminhao: rotas,
      pontosBacklog: pool,
      bounds: boundsCalc,
      semCoordenadas: missing,
    };
  }, [data, consolidadosByPedido]);

  return (
    <div className="space-y-3">
      <div
        className={`${compacto ? "h-[calc(100vh-260px)] min-h-[420px]" : "h-[70vh]"} w-full rounded-xl border overflow-hidden shadow-sm`}
      >
        <MapContainer center={BASE_AMERICANA} zoom={11} className="h-full w-full" scrollWheelZoom>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {bounds && <FitBoundsOnMarkers bounds={bounds} />}

          {rotasCaminhao.map((rota) =>
            rota.pontos.length >= 2 ? (
              <Polyline
                key={`line-${rota.veiculoId}`}
                positions={rota.pontos}
                pathOptions={{ color: rota.cor, weight: 3, opacity: 0.85 }}
              />
            ) : null,
          )}

          {rotasCaminhao.flatMap((rota) =>
            rota.marcadores.map((p) => (
              <Marker
                key={p.key}
                position={[p.lat, p.lng]}
                icon={criarIconeCor(p.cor, p.numero)}
                draggable={!!onCorrigir}
                eventHandlers={{
                  dragend: (e) => {
                    const ll = (e.target as L.Marker).getLatLng();
                    onCorrigir?.(p.idItem, ll.lat, ll.lng);
                  },
                }}
              >
                <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
                  {p.caminhao} · {p.numero}ª parada | {p.cliente} | Peso:{" "}
                  {p.peso.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} kg
                </Tooltip>
              </Marker>
            )),
          )}

          {pontosBacklog.map((p) => (
            <Marker
              key={p.key}
              position={[p.lat, p.lng]}
              icon={criarIconeCor(p.cor)}
              draggable={!!onCorrigir}
              eventHandlers={{
                dragend: (e) => {
                  const ll = (e.target as L.Marker).getLatLng();
                  onCorrigir?.(p.idItem, ll.lat, ll.lng);
                },
              }}
            >
              <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
                Pedido: {p.numeroPedido} | Cliente: {p.cliente} | Peso:{" "}
                {p.peso.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} kg
              </Tooltip>
            </Marker>
          ))}
        </MapContainer>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        {rotasCaminhao.map((rota) => (
          <span key={rota.veiculoId} className="inline-flex items-center gap-1.5">
            <span
              className="inline-block h-3 w-3 rounded-full border border-white shadow-sm"
              style={{ background: rota.cor }}
            />
            {rota.veiculoNome}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block h-3 w-3 rounded-full border border-white shadow-sm"
            style={{ background: COR_BACKLOG }}
          />
          Fila / Backlog / Local
        </span>
        {semCoordenadas > 0 && (
          <span className="text-amber-700 dark:text-amber-400">
            {semCoordenadas} pedido(s) ainda sem localização — use “Localizar clientes”.
          </span>
        )}
      </div>
    </div>
  );
}

type StatusGeo = {
  rodando: boolean;
  total?: number;
  feitos?: number;
  clientes?: number;
  localizados?: number;
  nao_achados?: string[];
  erro?: string;
  sem_endereco_na_base?: boolean;
};

/** Localizar clientes (geocodificação em segundo plano) com progresso. */
function BarraLocalizacao({
  sessionId,
  onAtualizar,
}: {
  sessionId: string;
  onAtualizar: () => void;
}) {
  const [status, setStatus] = useState<StatusGeo | null>(null);
  const consultar = async () => {
    const r = await fetch(`/api/sessions/${sessionId}/geocodificar`);
    if (r.ok) setStatus((await r.json()) as StatusGeo);
  };
  useEffect(() => {
    void consultar();
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!status?.rodando) return;
    const t = setInterval(async () => {
      await consultar();
      onAtualizar();
    }, 3000);
    return () => clearInterval(t);
  }, [status?.rodando]); // eslint-disable-line react-hooks/exhaustive-deps
  const iniciar = async () => {
    const r = await fetch(`/api/sessions/${sessionId}/geocodificar`, { method: "POST" });
    if (r.ok) setStatus({ ...(status ?? {}), ...((await r.json()) as StatusGeo) });
    setTimeout(() => void consultar(), 1500);
  };
  const faltam = Math.max((status?.clientes ?? 0) - (status?.localizados ?? 0), 0);
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-4 py-2 text-sm">
      <span>
        <b>{status?.localizados ?? "…"}</b> de <b>{status?.clientes ?? "…"}</b> destinos localizados
        no mapa
      </span>
      {status?.rodando ? (
        <span className="text-muted-foreground">
          Localizando… {status.feitos ?? 0}/{status.total ?? 0} (cerca de 1,5 s por cliente, só na
          primeira vez)
        </span>
      ) : (
        faltam > 0 && (
          <button
            type="button"
            onClick={() => void iniciar()}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-accent-foreground"
          >
            Localizar {faltam} cliente(s)
          </button>
        )
      )}
      {status?.erro && <span className="text-destructive text-xs">{status.erro}</span>}
      {status?.sem_endereco_na_base && (
        <span className="text-amber-700 text-xs">
          Coloque a base-de-clientes1.xlsx (com endereço) na pasta do sistema.
        </span>
      )}
      {!!status?.nao_achados?.length && (
        <span className="text-amber-700 text-xs" title={status.nao_achados.join(", ")}>
          {status.nao_achados.length} não encontrado(s) — arraste o marcador para corrigir
        </span>
      )}
      <span className="ml-auto text-xs text-muted-foreground">
        Posição errada? Arraste o marcador: o sistema guarda.
      </span>
    </div>
  );
}

export function MapaRoteirizacao({
  data,
  consolidadosByPedido,
  sessionId,
  onAtualizar,
  compacto,
}: {
  data: Roteirizacao;
  consolidadosByPedido: Record<string, PedidoConsolidado>;
  sessionId?: string;
  onAtualizar?: () => void;
  compacto?: boolean;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const corrigir = sessionId
    ? async (idItem: string, lat: number, lon: number) => {
        await fetch(`/api/sessions/${sessionId}/geo/corrigir`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id_item: idItem, lat, lon }),
        });
        onAtualizar?.();
      }
    : undefined;

  if (!mounted) {
    return (
      <div className="h-[70vh] w-full rounded-xl border bg-muted flex items-center justify-center text-sm text-muted-foreground">
        Carregando mapa…
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {sessionId && <BarraLocalizacao sessionId={sessionId} onAtualizar={() => onAtualizar?.()} />}
      <MapaRoteirizacaoInner
        data={data}
        consolidadosByPedido={consolidadosByPedido}
        onCorrigir={corrigir}
        compacto={compacto}
      />
    </div>
  );
}
