import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";

import {
  confirmarValidacao,
  getConsolidados,
  getRoteirizacao,
  ingestSession,
  moverPedido,
  patchConsolidado,
  roteirizar,
  uploadSession,
} from "@/lib/api-client";
import type { ConsolidadoPatch, MoverPedidoRequest, Roteirizacao } from "@/lib/logistica-types";
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
  });

  const roteirizacaoQuery = useQuery({
    queryKey: ["roteirizacao", sessionId],
    queryFn: () => getRoteirizacao(sessionId!),
    enabled: !!sessionId,
    retry: false,
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
    }: {
      sid: string;
      regrasNovas?: Record<string, string>;
    }) => confirmarValidacao(sid, regrasNovas ?? {}),
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
    onSuccess: (data, { sid }) => {
      queryClient.setQueryData(["roteirizacao", sid], data.roteirizacao);
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
    moverMutation,
    patchConsolidadoDebounced,
  };
}
