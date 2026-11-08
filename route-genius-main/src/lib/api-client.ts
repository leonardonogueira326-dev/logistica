import type {
  AnteciparPedidoBody,
  DividirCargaRequest,
  OperacaoDivisao,
  ConsultaRepresentanteRequest,
  LiberacaoComercialRequest,
  EquipeVeiculo,
  ConsultaRepresentanteResponse,
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
  /** Adicionar ao quadro do dia desta sessão (segunda lista / adicional) */
  sessionId?: string | null;
}): Promise<UploadResponse> {
  const form = new FormData();
  if (files.sessionId) form.append("session_id", files.sessionId);
  if (files.pdf) form.append("pdf", files.pdf);
  if (files.xlsb) form.append("xlsb", files.xlsb);
  if (files.msg) form.append("msg", files.msg);

  return request<UploadResponse>("/sessions/upload", {
    method: "POST",
    body: form,
  });
}

/** Motorista, ajudante e placa do caminhão no dia. */
export async function definirEquipe(
  sessionId: string,
  veiculoId: string,
  equipe: EquipeVeiculo,
): Promise<MoverPedidoResponse> {
  return request<MoverPedidoResponse>(
    `/sessions/${sessionId}/veiculos/${encodeURIComponent(veiculoId)}/equipe`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(equipe) },
  );
}

/** Melhor ordem de entrega (OR-Tools) de um caminhão ou de todos os abertos. */
export async function otimizarSequencia(sessionId: string, veiculoId = ""): Promise<MoverPedidoResponse> {
  return request<MoverPedidoResponse>(`/sessions/${sessionId}/otimizar-sequencia`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ veiculo_id: veiculoId }),
  });
}

/** Fecha/reabre um caminhão: a sugestão automática não mexe em caminhão fechado. */
export async function fecharVeiculo(
  sessionId: string,
  veiculoId: string,
  fechado: boolean,
): Promise<MoverPedidoResponse> {
  return request<MoverPedidoResponse>(
    `/sessions/${sessionId}/veiculos/${encodeURIComponent(veiculoId)}/fechar`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fechado }) },
  );
}

/** Primeira vez monta o quadro; depois só sugere (não desfaz). recomecar=true refaz do zero. */
export async function roteirizarQuadro(sessionId: string, recomecar = false): Promise<Roteirizacao> {
  return request<Roteirizacao>(`/sessions/${sessionId}/roteirizar${recomecar ? "?recomecar=true" : ""}`, {
    method: "POST",
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

export async function exportarRomaneioCaminhao(
  sessionId: string,
  caminhaoId: string,
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/sessions/${sessionId}/caminhao/${encodeURIComponent(caminhaoId)}/exportar`,
  );
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
  const hoje = new Date().toISOString().slice(0, 10);
  const filename =
    match?.[1] ?? `Romaneio_Caminhao_${caminhaoId}_${hoje}.xlsx`;
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

/** null = o quadro do dia ainda não foi montado (não é erro). */
export async function getRoteirizacao(sessionId: string): Promise<Roteirizacao | null> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/roteirizacao`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(res.statusText);
  return res.json() as Promise<Roteirizacao>;
}

export async function habilitarSegundaViagem(
  sessionId: string,
  veiculoId: string,
): Promise<Roteirizacao> {
  return request<Roteirizacao>(
    `/sessions/${sessionId}/segunda-viagem/${encodeURIComponent(veiculoId)}`,
    { method: "POST" },
  );
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

/** Pagamento antecipado: comercial liberou por e-mail. */
export async function registrarLiberacaoComercial(
  sessionId: string,
  body: LiberacaoComercialRequest,
): Promise<ConsultaRepresentanteResponse> {
  return request<ConsultaRepresentanteResponse>(`/sessions/${sessionId}/liberacao-comercial`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Item veio com peso zerado: logística informa o peso. */
export async function informarPeso(
  sessionId: string,
  body: { id: string; peso_kg: number },
): Promise<ConsultaRepresentanteResponse> {
  return request<ConsultaRepresentanteResponse>(`/sessions/${sessionId}/informar-peso`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Resposta do representante: pode carregar hoje? */
export async function registrarConsultaRepresentante(
  sessionId: string,
  body: ConsultaRepresentanteRequest,
): Promise<ConsultaRepresentanteResponse> {
  return request<ConsultaRepresentanteResponse>(`/sessions/${sessionId}/consulta-representante`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Dividir / ajustar / juntar / confirmar divisão de uma carga. */
export async function operarDivisao(
  sessionId: string,
  operacao: OperacaoDivisao,
): Promise<MoverPedidoResponse> {
  const rota = operacao.op === "dividir" ? "dividir" : `dividir/${operacao.op}`;
  return request<MoverPedidoResponse>(`/sessions/${sessionId}/${rota}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(operacao.body),
  });
}

/** Divide uma carga por peso; a nova parte fica na mesma coluna. */
export async function dividirCarga(
  sessionId: string,
  body: DividirCargaRequest,
): Promise<MoverPedidoResponse> {
  return request<MoverPedidoResponse>(`/sessions/${sessionId}/dividir`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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
