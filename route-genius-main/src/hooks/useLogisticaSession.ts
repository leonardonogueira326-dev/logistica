import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";

import {
  confirmarValidacao,
  anteciparPedido,
  operarDivisao,
  registrarConsultaRepresentante,
  registrarLiberacaoComercial,
  conferirFrete,
  ensinarFrase,
  informarPeso,
  getConsolidados,
  getRoteirizacao,
  ingestSession,
  habilitarSegundaViagem,
  moverPedido,
  patchConsolidado,
  roteirizar,
  roteirizarQuadro,
  fecharVeiculo,
  marcarNaoSaiu,
  definirEquipe,
  uploadSession,
} from "@/lib/api-client";
import type {
  EquipeVeiculo,
  AnteciparPedidoBody,
  ConsolidadoPatch,
  ConsultaRepresentanteRequest,
  LiberacaoComercialRequest,
  OperacaoDivisao,
  MoverPedidoRequest,
  Roteirizacao,
} from "@/lib/logistica-types";
import { COLUMN_BACKLOG } from "@/lib/logistica-types";
import { optimisticMoveRoteirizacao } from "@/lib/optimistic-move";
import { SESSION_KEY } from "@/lib/logistica-types";

export function getStoredSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(SESSION_KEY);
}

export function setStoredSessionId(id: string) {
  localStorage.setItem(SESSION_KEY, id);
}

export function useLogisticaSession(sessionId: string | null) {
  const queryClient = useQueryClient();

  const consolidadosQuery = useQuery({
    queryKey: ["consolidados", sessionId],
    queryFn: () => getConsolidados(sessionId!),
    enabled: !!sessionId,
    refetchInterval: (query) =>
      query.state.data?.consolidados.some((c) => c.status_ia === "PROCESSANDO_IA") ? 2000 : false,
  });

  const roteirizacaoQuery = useQuery({
    queryKey: ["roteirizacao", sessionId],
    queryFn: () => getRoteirizacao(sessionId!),
    enabled: !!sessionId,
    retry: false,
    // Enquanto o sistema localiza clientes no mapa, atualiza sozinho
    refetchInterval: (q) =>
      Object.values(q.state.data?.painel_veiculos ?? {}).some((p) => p.localizando) ? 4000 : false,
  });

  const uploadMutation = useMutation({
    mutationFn: uploadSession,
    onSuccess: (data) => {
      setStoredSessionId(data.session_id);
    },
  });

  const ingestMutation = useMutation({
    mutationFn: ingestSession,
    onSuccess: (_data, sid) => {
      queryClient.invalidateQueries({ queryKey: ["consolidados", sid] });
    },
  });

  const confirmMutation = useMutation({
    mutationFn: ({
      sid,
      regrasNovas,
      memoriaNovas,
    }: {
      sid: string;
      regrasNovas?: Record<string, string>;
      memoriaNovas?: Record<string, string>;
    }) => confirmarValidacao(sid, regrasNovas ?? {}, memoriaNovas ?? {}),
    onSuccess: (_data, { sid }) => {
      queryClient.invalidateQueries({ queryKey: ["consolidados", sid] });
    },
  });

  const roteirizarMutation = useMutation({
    mutationFn: roteirizar,
    onSuccess: (data, sid) => {
      queryClient.setQueryData(["roteirizacao", sid], data);
    },
  });

  /** Apaga o quadro do dia e monta tudo de novo (pede confirmação na tela). */
  const recomecarMutation = useMutation({
    mutationFn: (sid: string) => roteirizarQuadro(sid, true),
    onSuccess: (data, sid) => {
      queryClient.setQueryData(["roteirizacao", sid], data);
    },
  });

  const fecharMutation = useMutation({
    mutationFn: ({
      sid,
      veiculoId,
      fechado,
    }: {
      sid: string;
      veiculoId: string;
      fechado: boolean;
    }) => fecharVeiculo(sid, veiculoId, fechado),
    onSuccess: (data, { sid }) => {
      queryClient.setQueryData(["roteirizacao", sid], data.roteirizacao);
    },
  });

  const naoSaiuMutation = useMutation({
    mutationFn: ({
      sid,
      veiculoId,
      naoSaiu,
    }: {
      sid: string;
      veiculoId: string;
      naoSaiu: boolean;
    }) => marcarNaoSaiu(sid, veiculoId, naoSaiu),
    onSuccess: (data, { sid }) => {
      queryClient.setQueryData(["roteirizacao", sid], data.roteirizacao);
    },
  });

  const equipeMutation = useMutation({
    mutationFn: ({
      sid,
      veiculoId,
      equipe,
    }: {
      sid: string;
      veiculoId: string;
      equipe: EquipeVeiculo;
    }) => definirEquipe(sid, veiculoId, equipe),
    onSuccess: (data, { sid }) => {
      queryClient.setQueryData(["roteirizacao", sid], data.roteirizacao);
    },
  });

  const moverMutation = useMutation({
    mutationFn: ({ sid, body }: { sid: string; body: MoverPedidoRequest }) =>
      moverPedido(sid, body),
    onMutate: async ({ sid, body }) => {
      if (body.destino === COLUMN_BACKLOG && !body.motivo) {
        return { prev: undefined as Roteirizacao | undefined };
      }
      await queryClient.cancelQueries({ queryKey: ["roteirizacao", sid] });
      const prev = queryClient.getQueryData<Roteirizacao>(["roteirizacao", sid]);
      if (prev) {
        queryClient.setQueryData(
          ["roteirizacao", sid],
          optimisticMoveRoteirizacao(prev, body.numero_pedido, body.destino, body.motivo),
        );
      }
      return { prev };
    },
    onError: (_err, { sid }, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData(["roteirizacao", sid], ctx.prev);
      }
    },
    onSuccess: (data, { sid, body }) => {
      queryClient.setQueryData(["roteirizacao", sid], data.roteirizacao);
      if (body.liberar_representante) {
        queryClient.invalidateQueries({ queryKey: ["consolidados", sid] });
      }
    },
  });

  const consultaMutation = useMutation({
    mutationFn: ({ sid, body }: { sid: string; body: ConsultaRepresentanteRequest }) =>
      registrarConsultaRepresentante(sid, body),
    onSuccess: (_data, { sid }) => {
      queryClient.invalidateQueries({ queryKey: ["consolidados", sid] });
      queryClient.invalidateQueries({ queryKey: ["roteirizacao", sid] });
    },
  });

  const comercialMutation = useMutation({
    mutationFn: ({ sid, body }: { sid: string; body: LiberacaoComercialRequest }) =>
      registrarLiberacaoComercial(sid, body),
    onSuccess: (_data, { sid }) => {
      queryClient.invalidateQueries({ queryKey: ["consolidados", sid] });
      queryClient.invalidateQueries({ queryKey: ["roteirizacao", sid] });
    },
  });

  const conferirFreteMutation = useMutation({
    mutationFn: ({ sid, body }: { sid: string; body: { ids: string[]; conferido: boolean } }) =>
      conferirFrete(sid, body),
    onSuccess: (_data, { sid }) => {
      queryClient.invalidateQueries({ queryKey: ["consolidados", sid] });
    },
  });

  const ensinarFraseMutation = useMutation({
    mutationFn: ({
      sid,
      body,
    }: {
      sid: string;
      body: { chave: string; exemplo: string; significado: string; status?: string };
    }) => ensinarFrase(sid, body),
    onSuccess: (_d, { sid }) => {
      queryClient.invalidateQueries({ queryKey: ["consolidados", sid] });
    },
  });

  const pesoMutation = useMutation({
    mutationFn: ({ sid, body }: { sid: string; body: { id: string; peso_kg: number } }) =>
      informarPeso(sid, body),
    onSuccess: (_data, { sid }) => {
      queryClient.invalidateQueries({ queryKey: ["consolidados", sid] });
      queryClient.invalidateQueries({ queryKey: ["roteirizacao", sid] });
    },
  });

  const dividirMutation = useMutation({
    mutationFn: ({ sid, operacao }: { sid: string; operacao: OperacaoDivisao }) =>
      operarDivisao(sid, operacao),
    onSuccess: (data, { sid }) => {
      queryClient.setQueryData(["roteirizacao", sid], data.roteirizacao);
    },
  });

  const anteciparMutation = useMutation({
    mutationFn: ({ sid, body }: { sid: string; body: AnteciparPedidoBody }) =>
      anteciparPedido(sid, body),
    onSuccess: (data, { sid }) => {
      queryClient.setQueryData(["roteirizacao", sid], data.roteirizacao);
      queryClient.invalidateQueries({ queryKey: ["consolidados", sid] });
    },
  });

  const segundaViagemMutation = useMutation({
    mutationFn: ({ sid, veiculoId }: { sid: string; veiculoId: string }) =>
      habilitarSegundaViagem(sid, veiculoId),
    onSuccess: (data, { sid }) => {
      queryClient.setQueryData(["roteirizacao", sid], data);
    },
  });

  const debounceTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const patchConsolidadoDebounced = useCallback(
    (sid: string, pedidoNorm: string, patch: ConsolidadoPatch) => {
      const key = `${pedidoNorm}:${Object.keys(patch).join(",")}`;
      const existing = debounceTimers.current.get(key);
      if (existing) clearTimeout(existing);

      debounceTimers.current.set(
        key,
        setTimeout(async () => {
          await patchConsolidado(sid, pedidoNorm, patch);
          queryClient.invalidateQueries({ queryKey: ["consolidados", sid] });
          debounceTimers.current.delete(key);
        }, 300),
      );
    },
    [queryClient],
  );

  return {
    consolidadosQuery,
    roteirizacaoQuery,
    uploadMutation,
    ingestMutation,
    confirmMutation,
    roteirizarMutation,
    recomecarMutation,
    fecharMutation,
    naoSaiuMutation,
    equipeMutation,
    moverMutation,
    anteciparMutation,
    dividirMutation,
    consultaMutation,
    comercialMutation,
    conferirFreteMutation,
    ensinarFraseMutation,
    pesoMutation,
    segundaViagemMutation,
    patchConsolidadoDebounced,
  };
}
