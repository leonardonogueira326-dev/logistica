"""Quadro do dia: montagem dos caminhões (mover, dividir, equipe, fechar, romaneio)."""

from __future__ import annotations

from io import BytesIO
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.schemas import (  # noqa: E402
    AnteciparPedidoBodySchema,
    AnteciparPedidoResponseSchema,
    AjustarDivisaoSchema,
    CargaRefSchema,
    DividirCargaSchema,
    EquipeVeiculoSchema,
    FecharVeiculoSchema,
    NaoSaiuSchema,
    MoverPedidoSchema,
    MoverLoteSchema,
    MoverPedidoResponseSchema,
    RoteirizacaoSchema,
)
from api.session_store import SessionNotFoundError, store  # noqa: E402
from motor_logistica import MotorLogistica  # noqa: E402
import config  # noqa: E402
from normalizador import mesma_linha  # noqa: E402
from pendencias import (  # noqa: E402
    CONSULTA_REPRESENTANTE,
    PAGAMENTO_ANTECIPADO,
    PESO_ZERADO,
    pendencias as calc_pendencias,
)
from equipe import guardar_nomes, lembrar  # noqa: E402
from gerador_romaneio import (  # noqa: E402
    nome_arquivo_romaneio,
    nome_arquivo_romaneio_caminhao,
)
from api.servicos.quadro import (  # noqa: E402
    _COLUNAS_NAO_VEICULO,
    _definir_transportadora,
    _enriquecer_teo_motor,
    _get_active_consolidados,
    _limite_consulta,
    _motor_from_roteirizacao,
    _operar_divisao,
    _patch_consolidado_session,
    _romaneio_planilha,
    _roteirizacao_from_motor,
    _tirar_transportadora_a_definir,
)

router = APIRouter(prefix="/api/sessions", tags=["montagem"])


@router.post("/{session_id}/veiculos/{veiculo_id}/equipe", response_model=MoverPedidoResponseSchema)
def definir_equipe(session_id: str, veiculo_id: str, body: EquipeVeiculoSchema) -> MoverPedidoResponseSchema:
    """Motorista, ajudante e placa do caminhão no dia (vai para o romaneio)."""

    def aplicar(m: MotorLogistica) -> tuple[bool, str]:
        dados = {k: getattr(body, k).strip().upper() for k in ("motorista", "ajudante", "placa")}
        m.equipe_por_veiculo[veiculo_id] = dados
        lembrar(veiculo_id, dados)
        guardar_nomes(dados)
        return True, "Equipe salva."

    return _operar_divisao(session_id, aplicar)


@router.post("/{session_id}/veiculos/{veiculo_id}/fechar", response_model=MoverPedidoResponseSchema)
def fechar_veiculo(session_id: str, veiculo_id: str, body: FecharVeiculoSchema) -> MoverPedidoResponseSchema:
    """Caminhão fechado: a sugestão automática não coloca nem tira nada dele."""
    return _operar_divisao(session_id, lambda m: m.fechar_veiculo(veiculo_id, body.fechado))


@router.post("/{session_id}/veiculos/{veiculo_id}/nao-saiu", response_model=MoverPedidoResponseSchema)
def marcar_nao_saiu(session_id: str, veiculo_id: str, body: NaoSaiuSchema) -> MoverPedidoResponseSchema:
    """Motorista faltou / caminhão quebrou: a carga passa para o próximo dia."""
    return _operar_divisao(session_id, lambda m: m.marcar_nao_saiu(veiculo_id, body.nao_saiu))


@router.get("/{session_id}/roteirizacao", response_model=RoteirizacaoSchema)
def get_roteirizacao(session_id: str) -> RoteirizacaoSchema:
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    data.setdefault("coletas", [])
    data.setdefault("backlog_futuro", [])
    data.setdefault("backlog_local", [])
    data.setdefault("itens_retorno_por_veiculo", {})
    data.setdefault("viagens_retorno_habilitadas", [])
    data.setdefault("metricas_retorno", {})
    motor = _motor_from_roteirizacao(data)
    if _tirar_transportadora_a_definir(motor, session_id):
        store.save_roteirizacao(session_id, motor.para_dict(), desfazivel=False)
    _enriquecer_teo_motor(motor)
    return _roteirizacao_from_motor(motor, session_id)


@router.get("/{session_id}/exportar-romaneio")
def exportar_romaneio(session_id: str) -> StreamingResponse:
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    try:
        conteudo, dia = _romaneio_planilha(session_id, data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao gerar romaneio: {exc}") from exc

    filename = f"ROTA DIARIA {dia.strftime('%d_%m_%Y')}.xlsx" if dia else nome_arquivo_romaneio(session_id)
    return StreamingResponse(
        BytesIO(conteudo),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/caminhao/{caminhao_id}/exportar")
def exportar_romaneio_caminhao(session_id: str, caminhao_id: str) -> StreamingResponse:
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    try:
        conteudo, dia = _romaneio_planilha(session_id, data, somente_veiculo=caminhao_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao gerar romaneio: {exc}") from exc

    filename = nome_arquivo_romaneio_caminhao(caminhao_id)
    return StreamingResponse(
        BytesIO(conteudo),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{session_id}/segunda-viagem/{veiculo_id}", response_model=RoteirizacaoSchema)
def habilitar_segunda_viagem(session_id: str, veiculo_id: str) -> RoteirizacaoSchema:
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    motor = _motor_from_roteirizacao(data)
    ok, err = motor.habilitar_segunda_viagem(veiculo_id)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    payload = motor.para_dict()
    store.save_roteirizacao(session_id, payload)
    return _roteirizacao_from_motor(motor, session_id)


@router.post("/{session_id}/desfazer", response_model=MoverPedidoResponseSchema)
def desfazer(session_id: str) -> MoverPedidoResponseSchema:
    """Volta o quadro para antes da última mudança (mover, dividir, sugerir, otimizar…)."""
    anterior = store.desfazer_roteirizacao(session_id)
    if anterior is None:
        raise HTTPException(status_code=400, detail="Nada para desfazer.")
    motor = _motor_from_roteirizacao(anterior)
    _enriquecer_teo_motor(motor)
    return MoverPedidoResponseSchema(
        ok=True, warning="Última mudança desfeita.", roteirizacao=_roteirizacao_from_motor(motor, session_id)
    )


@router.post("/{session_id}/mover-lote", response_model=MoverPedidoResponseSchema)
def mover_lote(session_id: str, body: MoverLoteSchema) -> MoverPedidoResponseSchema:
    """
    Vários cards de uma vez (seleção múltipla / cliente inteiro). Um passo só no
    "Desfazer". O que não pode ir (travado, precisa do representante, sem espaço
    sem forçar) fica onde está e é avisado.
    """
    if body.liberar_representante and body.transportadora_codigo.strip():
        _definir_transportadora(session_id, body.ids, body.transportadora_codigo)
    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")
    motor = _motor_from_roteirizacao(data)
    para_veiculo = body.destino.upper() not in _COLUNAS_NAO_VEICULO
    try:
        _, consolidados, _ = _get_active_consolidados(session_id)
    except HTTPException:
        consolidados = []
    limite = _limite_consulta()
    movidos, ficaram, liberados = 0, [], []
    for id_carga in dict.fromkeys(body.ids):
        ref = next((c for c in consolidados if mesma_linha(c, id_carga.split("@")[0])), None)
        nome = (ref.cliente if ref else id_carga)[:30]
        if para_veiculo and ref is not None:
            abertas = calc_pendencias(ref, limite)
            if PAGAMENTO_ANTECIPADO in abertas or PESO_ZERADO in abertas:
                ficaram.append(f"{nome} (travado)")
                continue
            if CONSULTA_REPRESENTANTE in abertas:
                if not body.liberar_representante:
                    ficaram.append(f"{nome} (falta o representante liberar)")
                    continue
                liberados.append(ref)
        ok, aviso = motor.mover_pedido(id_carga, body.destino, body.motivo, forcar=body.forcar)
        if ok:
            movidos += 1
        else:
            ficaram.append(f"{nome} ({aviso or 'não coube'})")
            if ref in liberados:
                liberados.remove(ref)
    if not movidos:
        raise HTTPException(status_code=400, detail="Nada foi movido: " + "; ".join(ficaram))
    store.save_roteirizacao(session_id, motor.para_dict())
    agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    for ref in liberados:
        quem = body.autorizado_por.strip() or ref.representante
        _patch_consolidado_session(
            session_id,
            ref.id_item or ref.numero_pedido,
            {
                "consulta_representante": "LIBERADO",
                "consulta_em": agora,
                "representante_autorizou": quem,
                "motivo_adiantamento": f"Liberado pelo representante {quem}",
                "auditoria": (ref.auditoria + f" | CONSULTA REPRESENTANTE {agora}: Liberado por {quem} (Kanban)").strip(" |"),
            },
        )
    aviso = f"{movidos} {'card movido' if movidos == 1 else 'cards movidos'}."
    if ficaram:
        aviso += " Ficaram: " + "; ".join(ficaram)
    return MoverPedidoResponseSchema(ok=True, warning=aviso, roteirizacao=_roteirizacao_from_motor(motor, session_id))


@router.post("/{session_id}/mover", response_model=MoverPedidoResponseSchema)
def mover_pedido(session_id: str, body: MoverPedidoSchema) -> MoverPedidoResponseSchema:
    if body.liberar_representante and body.transportadora_codigo.strip():
        _definir_transportadora(session_id, [body.numero_pedido], body.transportadora_codigo)
    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    motor = _motor_from_roteirizacao(data)

    # Para caminhão: linha travada (comercial / peso zerado) não sobe;
    # consulta ao representante precisa da confirmação do operador.
    ref = None
    if body.destino.upper() not in _COLUNAS_NAO_VEICULO:
        try:
            _, consolidados, _ = _get_active_consolidados(session_id)
        except HTTPException:
            consolidados = []
        id_linha = body.numero_pedido.split("@")[0]
        ref = next((c for c in consolidados if mesma_linha(c, id_linha)), None)
        if ref is not None:
            abertas = calc_pendencias(ref, _limite_consulta())
            travas = [p for p in abertas if p in (PAGAMENTO_ANTECIPADO, PESO_ZERADO)]
            if travas:
                nomes = {PAGAMENTO_ANTECIPADO: "aguardando liberação do comercial", PESO_ZERADO: "peso zerado"}
                raise HTTPException(
                    status_code=400,
                    detail="Linha travada (" + ", ".join(nomes[t] for t in travas)
                    + "). Resolva na página Pendências.",
                )
            if CONSULTA_REPRESENTANTE in abertas and not body.liberar_representante:
                raise HTTPException(
                    status_code=409,
                    detail="Confirme que o representante liberou antes de carregar.",
                )

    ok, warning = motor.mover_pedido(
        body.numero_pedido,
        body.destino,
        body.motivo,
        forcar=body.forcar,
    )

    if not ok:
        raise HTTPException(status_code=400, detail=warning or "Não foi possível mover o pedido.")

    payload = motor.para_dict()
    store.save_roteirizacao(session_id, payload)

    if ref is not None and body.liberar_representante:
        agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
        quem = body.autorizado_por.strip() or ref.representante
        _patch_consolidado_session(
            session_id,
            ref.id_item or ref.numero_pedido,
            {
                "consulta_representante": "LIBERADO",
                "consulta_em": agora,
                "representante_autorizou": quem,
                "motivo_adiantamento": f"Liberado pelo representante {quem}",
                "auditoria": (ref.auditoria + f" | CONSULTA REPRESENTANTE {agora}: Liberado por {quem} (Kanban)").strip(" |"),
            },
        )
    return MoverPedidoResponseSchema(
        ok=True,
        warning=warning,
        roteirizacao=_roteirizacao_from_motor(motor, session_id),
    )


@router.post("/{session_id}/dividir", response_model=MoverPedidoResponseSchema)
def dividir_carga(session_id: str, body: DividirCargaSchema) -> MoverPedidoResponseSchema:
    """Divide uma carga por peso; a nova parte fica na mesma coluna."""
    data = store.load_roteirizacao(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    motor = _motor_from_roteirizacao(data)
    ok, mensagem = motor.dividir_carga(body.id_carga, body.peso_kg)
    if not ok:
        raise HTTPException(status_code=400, detail=mensagem)

    store.save_roteirizacao(session_id, motor.para_dict())
    return MoverPedidoResponseSchema(
        ok=True,
        warning=mensagem,
        roteirizacao=_roteirizacao_from_motor(motor, session_id),
    )


@router.post("/{session_id}/dividir/ajustar", response_model=MoverPedidoResponseSchema)
def ajustar_divisao(session_id: str, body: AjustarDivisaoSchema) -> MoverPedidoResponseSchema:
    """Ajuste fino: esta parte fica com peso_kg; a diferença vai para a outra parte."""
    return _operar_divisao(
        session_id,
        lambda m: m.ajustar_divisao(body.id_carga, body.peso_kg, body.id_carga_contrapartida),
    )


@router.post("/{session_id}/dividir/juntar", response_model=MoverPedidoResponseSchema)
def juntar_partes(session_id: str, body: CargaRefSchema) -> MoverPedidoResponseSchema:
    """Desfaz a divisão: todas as partes voltam para este card."""
    return _operar_divisao(session_id, lambda m: m.juntar_partes(body.id_carga))


@router.post("/{session_id}/dividir/confirmar", response_model=MoverPedidoResponseSchema)
def confirmar_divisao(session_id: str, body: CargaRefSchema) -> MoverPedidoResponseSchema:
    """Operador conferiu a divisão automática."""
    return _operar_divisao(session_id, lambda m: m.confirmar_divisao(body.id_carga))


@router.post("/{session_id}/antecipar", response_model=AnteciparPedidoResponseSchema)
def antecipar_pedido(
    session_id: str,
    body: AnteciparPedidoBodySchema,
) -> AnteciparPedidoResponseSchema:
    try:
        store.session_path(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    rote_data = store.load_roteirizacao(session_id)
    if not rote_data:
        raise HTTPException(status_code=404, detail="Roteirização não executada.")

    motivo = (body.motivo_adiantamento or "").strip()
    if not motivo:
        raise HTTPException(status_code=400, detail="Informe o motivo do adiantamento.")

    rep = (body.representante_autorizou or "").strip()
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    audit_linha = f"ANTECIPADO em {agora}: {motivo}"
    if rep:
        audit_linha += f" | Autorizado por: {rep}"

    _, consolidados, _ = _get_active_consolidados(session_id)
    pedido_ref = next(
        (c for c in consolidados if mesma_linha(c, body.numero_pedido)),
        None,
    )
    if not pedido_ref:
        raise HTTPException(status_code=404, detail=f"Pedido {body.numero_pedido} não encontrado.")

    auditoria = (pedido_ref.auditoria + " | " + audit_linha).strip(" |")
    ok_patch = _patch_consolidado_session(
        session_id,
        body.numero_pedido,
        {
            "data_prevista_recebimento": "",
            "motivo_adiantamento": motivo,
            "representante_autorizou": rep,
            "status": config.COD_LIBERADO,
            "auditoria": auditoria,
        },
    )
    if not ok_patch:
        raise HTTPException(status_code=404, detail="Não foi possível atualizar o consolidado.")

    motor = _motor_from_roteirizacao(rote_data)

    ok, err, destino = motor.antecipar_para_hoje(body.numero_pedido)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    payload = motor.para_dict()
    store.save_roteirizacao(session_id, payload)

    destino_msg = {
        "BACKLOG": "fila de alocação de hoje",
    }.get(destino, destino)
    if destino not in ("BACKLOG",):
        for r in motor.rotas:
            if r.veiculo_id == destino:
                destino_msg = r.veiculo_nome
                break

    return AnteciparPedidoResponseSchema(
        ok=True,
        session_id=session_id,
        numero_pedido=body.numero_pedido,
        destino=destino,
        message=f"Pedido antecipado e alocado em {destino_msg}.",
        roteirizacao=_roteirizacao_from_motor(motor, session_id),
    )
