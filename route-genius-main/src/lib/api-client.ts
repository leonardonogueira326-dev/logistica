import type {
  AnteciparPedidoBody,
  AnteciparPedidoResponse,
  ConfigResponse,
  ConfiguracaoOperacional,
  ConsolidadoPatch,
  ConsolidadosList,
  HistoricoResponse,
  IngestaoResponse,
  MoverPedidoRequest,
  MoverPedidoResponse,
  PedidoManualBody,
  Roteirizacao,
  SetupResponse,
  UploadResponse,
  ValidacaoConfirmar,
} from "./logistica-types";

const API_BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export async function uploadSession(files: {
  pdf?: File;
  xlsb?: File;
  msg?: File;
}): Promise<UploadResponse> {
  const form = new FormData();
  if (files.pdf) form.append("pdf", files.pdf);
  if (files.xlsb) form.append("xlsb", files.xlsb);
  if (files.msg) form.append("msg", files.msg);

  return request<UploadResponse>("/sessions/upload", {
    method: "POST",
    body: form,
  });
}

export async function ingestSession(sessionId: string): Promise<IngestaoResponse> {
  return request<IngestaoResponse>(`/sessions/${sessionId}/ingest`, { method: "POST" });
}

export async function getConsolidados(sessionId: string): Promise<ConsolidadosList> {
  return request<ConsolidadosList>(`/sessions/${sessionId}/consolidados`);
}

export async function patchConsolidado(
  sessionId: string,
  pedidoNorm: string,
  patch: ConsolidadoPatch,
): Promise<void> {
  await request(`/sessions/${sessionId}/consolidados/${encodeURIComponent(pedidoNorm)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function confirmarValidacao(
  sessionId: string,
  regrasNovas: Record<string, string> = {},
  memoriaNovas: Record<string, string> = {},
): Promise<ValidacaoConfirmar> {
  return request<ValidacaoConfirmar>(`/sessions/${sessionId}/validacao/confirmar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ regras_novas: regrasNovas, memoria_novas: memoriaNovas }),
  });
}

export async function exportarRomaneio(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/exportar-romaneio`);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="?([^";\n]+)"?/i);
  const filename = match?.[1] ?? `romaneio_${sessionId.slice(0, 8)}.xlsx`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function roteirizar(sessionId: string): Promise<Roteirizacao> {
  return request<Roteirizacao>(`/sessions/${sessionId}/roteirizar`, { method: "POST" });
}

export async function getRoteirizacao(sessionId: string): Promise<Roteirizacao> {
  return request<Roteirizacao>(`/sessions/${sessionId}/roteirizacao`);
}

export async function moverPedido(
  sessionId: string,
  body: MoverPedidoRequest,
): Promise<MoverPedidoResponse> {
  return request<MoverPedidoResponse>(`/sessions/${sessionId}/mover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function healthCheck(): Promise<{ status: string }> {
  return request("/health");
}

export async function getConfig(): Promise<ConfigResponse> {
  return request<ConfigResponse>("/config");
}

export async function saveConfig(config: ConfiguracaoOperacional): Promise<ConfigResponse> {
  return request<ConfigResponse>("/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

/** @deprecated Use getConfig */
export async function getSetup(): Promise<SetupResponse> {
  const resp = await getConfig();
  return { config: resp.config, arquivo: resp.arquivo };
}

/** @deprecated Use saveConfig */
export async function saveSetup(config: ConfiguracaoOperacional): Promise<SetupResponse> {
  const resp = await saveConfig(config);
  return { config: resp.config, arquivo: resp.arquivo };
}

export async function buscarHistorico(q: string, limite = 20): Promise<HistoricoResponse> {
  const params = new URLSearchParams({ q, limite: String(limite) });
  return request<HistoricoResponse>(`/historico?${params}`);
}

export async function anteciparPedido(
  sessionId: string,
  body: AnteciparPedidoBody,
): Promise<AnteciparPedidoResponse> {
  return request<AnteciparPedidoResponse>(`/sessions/${sessionId}/antecipar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
export async function criarPedidoManual(body: PedidoManualBody): Promise<{ ok: boolean; message: string }> {
  return request("/pedidos-manuais", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
