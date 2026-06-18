import {
  COLUMN_BACKLOG,
  COLUMN_COLETAS,
  type ItemRota,
  type Roteirizacao,
} from "@/lib/logistica-types";

function findPedidoLocation(data: Roteirizacao, numeroPedido: string): string | null {
  for (const [vid, itens] of Object.entries(data.itens_por_veiculo)) {
    if (itens.some((i) => i.numero_pedido === numeroPedido)) return vid;
  }
  if (data.backlog.some((b) => b.numero_pedido === numeroPedido)) return COLUMN_BACKLOG;
  if ((data.coletas ?? []).some((c) => c.numero_pedido === numeroPedido)) return COLUMN_COLETAS;
  return null;
}

function extractPedido(
  data: Roteirizacao,
  origem: string,
  numeroPedido: string,
): ItemRota | Record<string, string> | null {
  if (origem === COLUMN_BACKLOG) {
    const b = data.backlog.find((x) => x.numero_pedido === numeroPedido);
    return b ?? null;
  }
  if (origem === COLUMN_COLETAS) {
    const c = (data.coletas ?? []).find((x) => x.numero_pedido === numeroPedido);
    return c ?? null;
  }
  const itens = data.itens_por_veiculo[origem] ?? [];
  return itens.find((i) => i.numero_pedido === numeroPedido) ?? null;
}

function toItemRota(p: ItemRota | Record<string, string>): ItemRota {
  if ("sequencia_lifo" in p && typeof p.sequencia_lifo === "string") {
    return p as ItemRota;
  }
  return {
    numero_pedido: String(p.numero_pedido ?? ""),
    cliente: String(p.cliente ?? ""),
    cliente_codigo: String(p.cliente_codigo ?? ""),
    representante: String(p.representante ?? ""),
    bairro_destino: String(p.bairro_destino ?? ""),
    cidade_destino: String(p.cidade_destino ?? ""),
    cep_destino: String(p.cep_destino ?? ""),
    rota_logistica: String(p.rota_logistica ?? ""),
    peso_kg: Number(p.peso_kg ?? 0),
    sequencia_lifo: "0",
    is_spyder: String(p.is_spyder ?? "NAO"),
    is_dimensao_longa: String(p.is_dimensao_longa ?? "NAO"),
    enriquecido_mestre: String(p.enriquecido_mestre ?? "NAO"),
  };
}

/** Atualização otimista do Kanban antes da resposta da API. */
export function optimisticMoveRoteirizacao(
  data: Roteirizacao,
  numeroPedido: string,
  destino: string,
  motivo?: string,
): Roteirizacao {
  const origem = findPedidoLocation(data, numeroPedido);
  if (!origem || origem === destino) return data;

  const pedido = extractPedido(data, origem, numeroPedido);
  if (!pedido) return data;

  const next: Roteirizacao = {
    ...data,
    itens_por_veiculo: { ...data.itens_por_veiculo },
    backlog: [...data.backlog],
    coletas: [...(data.coletas ?? [])],
  };

  if (origem !== COLUMN_BACKLOG && origem !== COLUMN_COLETAS) {
    next.itens_por_veiculo[origem] = (next.itens_por_veiculo[origem] ?? []).filter(
      (i) => i.numero_pedido !== numeroPedido,
    );
  } else if (origem === COLUMN_BACKLOG) {
    next.backlog = next.backlog.filter((b) => b.numero_pedido !== numeroPedido);
  } else {
    next.coletas = next.coletas.filter((c) => c.numero_pedido !== numeroPedido);
  }

  const item = toItemRota(pedido);

  if (destino === COLUMN_BACKLOG) {
    next.backlog.push({
      numero_pedido: item.numero_pedido,
      cliente: item.cliente,
      representante: item.representante,
      cidade_destino: item.cidade_destino,
      rota_logistica: item.rota_logistica,
      peso_kg: String(item.peso_kg),
      motivo: motivo ?? "DECISAO OPERADOR",
    });
  } else if (destino === COLUMN_COLETAS) {
    next.coletas.push({
      numero_pedido: item.numero_pedido,
      cliente: item.cliente,
      bairro_destino: item.bairro_destino,
      cidade_destino: item.cidade_destino,
      peso_kg: String(item.peso_kg),
      motivo: motivo ?? "COLETA",
    });
  } else {
    const list = [...(next.itens_por_veiculo[destino] ?? []), item];
    next.itens_por_veiculo[destino] = list;
  }

  return next;
}
