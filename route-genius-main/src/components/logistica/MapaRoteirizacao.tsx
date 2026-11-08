import L from "leaflet";
import { useEffect, useMemo, useState } from "react";
import {
  MapContainer,
  Marker,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";

import type { ItemRota, PedidoConsolidado, Roteirizacao } from "@/lib/logistica-types";

import "leaflet/dist/leaflet.css";

import iconRetina from "leaflet/dist/images/marker-icon-2x.png";
import icon from "leaflet/dist/images/marker-icon.png";
import iconShadow from "leaflet/dist/images/marker-shadow.png";

const BASE_AMERICANA: [number, number] = [-22.739, -47.331];

const CORES_CAMINHAO = [
  "#2563eb",
  "#dc2626",
  "#16a34a",
  "#9333ea",
  "#ea580c",
  "#0891b2",
  "#ca8a04",
  "#be185d",
];

const COR_BACKLOG = "rgba(100, 100, 100, 0.72)";

delete (L.Icon.Default.prototype as unknown as { _getIconUrl?: unknown })._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: iconRetina,
  iconUrl: icon,
  shadowUrl: iconShadow,
});

type PontoMapa = {
  key: string;
  lat: number;
  lng: number;
  numeroPedido: string;
  cliente: string;
  peso: number;
  cor: string;
  caminhao?: string;
};

type RotaCaminhao = {
  veiculoId: string;
  veiculoNome: string;
  cor: string;
  pontos: [number, number][];
  marcadores: PontoMapa[];
};

function criarIconeCor(cor: string) {
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
}: {
  data: Roteirizacao;
  consolidadosByPedido: Record<string, PedidoConsolidado>;
}) {
  const { rotasCaminhao, pontosBacklog, bounds, semCoordenadas } = useMemo(() => {
    const rotas: RotaCaminhao[] = data.rotas.map((rota, idx) => {
      const cor = CORES_CAMINHAO[idx % CORES_CAMINHAO.length];
      const itens = data.itens_por_veiculo[rota.veiculo_id] ?? [];
      const retorno = data.itens_retorno_por_veiculo[rota.veiculo_id] ?? [];
      const todosItens = [...itens, ...retorno];

      const marcadores: PontoMapa[] = [];
      const pontos: [number, number][] = [];

      for (const item of todosItens) {
        const ponto = itemParaPonto(item, cor, consolidadosByPedido, rota.veiculo_nome);
        if (!ponto) continue;
        marcadores.push(ponto);
        pontos.push([ponto.lat, ponto.lng]);
      }

      return {
        veiculoId: rota.veiculo_id,
        veiculoNome: rota.veiculo_nome,
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
        if (!coordsDoPedido(item.id_item || item.numero_pedido, item.cliente, item.peso_kg, consolidadosByPedido)) {
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
      <div className="h-[70vh] w-full rounded-xl border overflow-hidden shadow-sm">
        <MapContainer
          center={BASE_AMERICANA}
          zoom={11}
          className="h-full w-full"
          scrollWheelZoom
        >
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
                icon={criarIconeCor(p.cor)}
              >
                <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
                  Pedido: {p.numeroPedido} | Cliente: {p.cliente} | Peso:{" "}
                  {p.peso.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} kg
                </Tooltip>
              </Marker>
            )),
          )}

          {pontosBacklog.map((p) => (
            <Marker key={p.key} position={[p.lat, p.lng]} icon={criarIconeCor(p.cor)}>
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
            {semCoordenadas} pedido(s) sem coordenada no cadastro — não exibidos no mapa.
          </span>
        )}
      </div>
    </div>
  );
}

export function MapaRoteirizacao({
  data,
  consolidadosByPedido,
}: {
  data: Roteirizacao;
  consolidadosByPedido: Record<string, PedidoConsolidado>;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return (
      <div className="h-[70vh] w-full rounded-xl border bg-muted flex items-center justify-center text-sm text-muted-foreground">
        Carregando mapa…
      </div>
    );
  }

  return <MapaRoteirizacaoInner data={data} consolidadosByPedido={consolidadosByPedido} />;
}
