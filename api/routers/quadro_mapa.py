"""Quadro do dia: mapa, localização dos clientes, ordem e horários de entrega."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import (  # noqa: E402
    MoverPedidoResponseSchema,
)
from motor_logistica import MotorLogistica  # noqa: E402
from normalizador import mesma_linha, normalizar_codigo_cliente  # noqa: E402
import geocodificacao  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from api.servicos.quadro import (  # noqa: E402
    _contexto_agenda,
    _geocodificando,
    _gravar_agenda,
    _iniciar_geocodificacao,
    _linhas_do_quadro,
    _nomes_veiculos,
    _operar_divisao,
    _paradas_do_caminhao,
    _reagendar,
)

router = APIRouter(prefix="/api/sessions", tags=["mapa"])


@router.post("/{session_id}/geocodificar", tags=["mapa"])
def iniciar_geocodificacao(session_id: str) -> dict[str, Any]:
    """Botão "Localizar clientes" (o quadro também começa sozinho quando abre)."""
    return _iniciar_geocodificacao(session_id)


@router.get("/{session_id}/geocodificar", tags=["mapa"])
def status_geocodificacao(session_id: str) -> dict[str, Any]:
    linhas = _linhas_do_quadro(session_id)
    base, cache = geocodificacao.enderecos_base(), geocodificacao.carregar_cache()
    chaves = {geocodificacao.chave_da_linha(l, base) for l in linhas} - {""}
    return {
        **_geocodificando.get(session_id, {"rodando": False}),
        "clientes": len(chaves),
        "localizados": len(chaves & set(cache)),
        "sem_endereco_na_base": not base,
    }


class _PosicaoManual(BaseModel):
    id_item: str
    lat: float
    lon: float


@router.post("/{session_id}/geo/corrigir", tags=["mapa"])
def corrigir_posicao(session_id: str, body: _PosicaoManual) -> dict[str, Any]:
    """Operador arrastou o marcador: vale para este cliente daqui para frente."""
    linha = next((l for l in _linhas_do_quadro(session_id) if mesma_linha(l, body.id_item)), None)
    if not linha:
        raise HTTPException(status_code=404, detail="Linha não encontrada.")
    chave = geocodificacao.chave_da_linha(linha)
    geocodificacao.definir_manual(chave, body.lat, body.lon)
    return {"ok": True, "chave": chave}


class _OtimizarBody(BaseModel):
    veiculo_id: str = ""


@router.post("/{session_id}/otimizar-sequencia", response_model=MoverPedidoResponseSchema, tags=["mapa"])
def otimizar_sequencia(session_id: str, body: _OtimizarBody) -> MoverPedidoResponseSchema:
    """
    Melhor ordem de entrega (OR-Tools) — um caminhão ou todos os abertos.
    Objetivo: voltar mais cedo contando a espera até o cliente abrir (km desempata).
    """
    from otimizacao import otimizar

    ctx = _contexto_agenda(session_id)

    def aplicar(m: MotorLogistica) -> tuple[bool, str]:
        nomes = _nomes_veiculos(m)
        alvo = [body.veiculo_id] if body.veiculo_id else [v for v in m.itens_por_veiculo if v not in m.veiculos_fechados]
        partes = []
        for vid in alvo:
            if not m.itens_por_veiculo.get(vid):
                continue
            paradas = _paradas_do_caminhao(m, vid, ctx)
            r = otimizar(list(paradas.values()), ctx["deposito"], ctx["inicio_min"],
                         velocidade_kmh=ctx["velocidade"], descarga_min=ctx["descarga"],
                         velocidade_estrada_kmh=ctx["velocidade_estrada"], fator_afastar=ctx["fator_afastar"])
            m.aplicar_sequencia(vid, r["ordem"])
            m.recalcular_metricas(vid)
            m.sequencia_otimizada[vid] = m.assinatura_carga(vid)
            _gravar_agenda(m, vid, r["agenda"], paradas)
            texto = f"{nomes.get(vid, vid)}: volta {m.agenda[vid]['volta']}, {r['km_depois']:.0f} km"
            if r["aviso"]:
                texto += f" ({r['aviso'].rstrip('.')})"
            partes.append(texto)
        if not partes:
            return True, "Nada para otimizar (caminhões vazios ou fechados)."
        return True, "Ordem de entrega otimizada — " + "; ".join(partes) + "."

    return _operar_divisao(session_id, aplicar)


class _OrdemBody(BaseModel):
    # chaves das paradas (cliente|cidade) na ordem de entrega desejada
    chaves: list[str]


@router.post("/{session_id}/veiculos/{veiculo_id}/ordem", response_model=MoverPedidoResponseSchema)
def definir_ordem(session_id: str, veiculo_id: str, body: _OrdemBody) -> MoverPedidoResponseSchema:
    """O operador escolhe a ordem (Entregar primeiro / Subir / Descer). Vale como ordem definida."""
    ctx = _contexto_agenda(session_id)

    def aplicar(m: MotorLogistica) -> tuple[bool, str]:
        if not m.itens_por_veiculo.get(veiculo_id):
            return False, "Caminhão vazio."
        m.aplicar_sequencia(veiculo_id, [c.upper() for c in body.chaves])
        m.recalcular_metricas(veiculo_id)
        m.sequencia_otimizada[veiculo_id] = m.assinatura_carga(veiculo_id)
        _reagendar(m, veiculo_id, ctx)
        return True, f"Ordem ajustada — volta prevista {m.agenda.get(veiculo_id, {}).get('volta', '')}."

    return _operar_divisao(session_id, aplicar)


class _HorarioClienteBody(BaseModel):
    cliente_codigo: str
    horario: str = ""  # "" apaga


@router.post("/{session_id}/horario-cliente", response_model=MoverPedidoResponseSchema)
def horario_cliente(session_id: str, body: _HorarioClienteBody) -> MoverPedidoResponseSchema:
    """Guarda o horário de recebimento do cliente (vale daqui para frente, nos dois PCs)."""
    import horarios_clientes

    try:
        horarios_clientes.salvar(body.cliente_codigo, body.horario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    ctx = _contexto_agenda(session_id)
    cod = normalizar_codigo_cliente(body.cliente_codigo)

    def aplicar(m: MotorLogistica) -> tuple[bool, str]:
        for vid, itens in m.itens_por_veiculo.items():
            if any(normalizar_codigo_cliente(i.cliente_codigo) == cod for i in itens):
                _reagendar(m, vid, ctx)
        txt = f"Horário de recebimento salvo: {body.horario}." if body.horario.strip() else "Horário do cliente apagado (vale o padrão)."
        return True, txt + " Use “Otimizar” para refazer a ordem com ele."

    return _operar_divisao(session_id, aplicar)
