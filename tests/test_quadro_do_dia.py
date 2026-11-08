"""
O quadro do dia é do operador: o PDF só traz informação.

- "Sugerir alocação" distribui só o que está sem lugar; não desfaz nada.
- Caminhão fechado: a sugestão não coloca nem tira nada dele.
- Segunda lista do dia / adicional: entra no mesmo quadro, na fila.
- Pendência que volta: a linha sai do caminhão para "Parados".
"""
from __future__ import annotations

from models import PedidoConsolidado
from motor_logistica import MotorLogistica


def _linha(n: int, peso: float = 300, cidade: str = "SAO PAULO", **extra) -> PedidoConsolidado:
    base = dict(
        numero_pedido=f"00{n}000/26/001",
        id_item=f"00{n}000/26/001#00{n}111/26",
        of_ano=f"00{n}111/26",
        cliente=f"CLIENTE {n}",
        cliente_codigo=f"9{n:04d}",
        peso_kg=peso,
        cidade_destino=cidade,
        estado_destino="SAO PAULO",
        status="LIBERADO",
        data_referencia="2026-06-19",
    )
    base.update(extra)
    return PedidoConsolidado(**base)


def _onde(motor: MotorLogistica, id_item: str) -> str | None:
    for vid, itens in motor.itens_por_veiculo.items():
        if any(i.id_item == id_item for i in itens):
            return vid
    for nome in ("backlog", "backlog_futuro", "backlog_local"):
        if any(b.get("id_item") == id_item for b in getattr(motor, nome)):
            return nome
    return None


def test_sugerir_nao_desfaz_o_que_o_operador_montou():
    linhas = [_linha(1), _linha(2), _linha(3)]
    motor = MotorLogistica()
    motor.alocar_frota(linhas)
    caminhao = _onde(motor, linhas[1].id_item)
    assert caminhao and caminhao.startswith("11.180") or caminhao

    # operador tira a linha 1 para a fila (decisão dele)
    ok, _ = motor.mover_pedido(linhas[0].id_item, "BACKLOG", motivo="Cliente pediu amanhã")
    assert ok
    antes = {l.id_item: _onde(motor, l.id_item) for l in linhas}

    alocadas, _ = motor.sugerir_alocacao(linhas)
    depois = {l.id_item: _onde(motor, l.id_item) for l in linhas}
    assert depois == antes, "a sugestão mexeu no que o operador montou"
    assert alocadas == 0


def test_linhas_novas_do_dia_entram_na_fila_e_a_sugestao_aloca_sem_mexer_no_resto():
    primeira = [_linha(1), _linha(2)]
    motor = MotorLogistica()
    motor.alocar_frota(primeira)
    antes = {l.id_item: _onde(motor, l.id_item) for l in primeira}

    segunda = [_linha(5, peso=200), _linha(6, peso=150)]
    assert motor.incluir_linhas_novas(segunda) == 2
    assert all(_onde(motor, l.id_item) == "backlog" for l in segunda)
    assert {l.id_item: _onde(motor, l.id_item) for l in primeira} == antes

    alocadas, fila = motor.sugerir_alocacao(primeira + segunda)
    assert alocadas == 2 and fila == 0
    assert all(_onde(motor, l.id_item).startswith(("11.", "10.")) for l in segunda)
    assert {l.id_item: _onde(motor, l.id_item) for l in primeira} == antes


def test_caminhao_fechado_nao_recebe_sugestao():
    primeira = [_linha(1)]
    motor = MotorLogistica()
    motor.alocar_frota(primeira)
    vid = _onde(motor, primeira[0].id_item)
    motor.fechar_veiculo(vid, True)

    nova = _linha(7, peso=100)
    motor.incluir_linhas_novas([nova])
    motor.sugerir_alocacao(primeira + [nova])
    assert _onde(motor, nova.id_item) != vid
    assert [i.id_item for i in motor.itens_por_veiculo[vid]] == [primeira[0].id_item]

    motor.fechar_veiculo(vid, False)
    assert vid not in motor.veiculos_fechados


def test_pendencia_que_volta_tira_a_linha_do_caminhao():
    l = _linha(1)
    motor = MotorLogistica()
    motor.alocar_frota([l])
    vid = _onde(motor, l.id_item)
    saiu = motor.tirar_do_caminhao_por_pendencia(l.id_item, "Pagamento antecipado — aguardando liberação do comercial")
    assert saiu
    assert _onde(motor, l.id_item) == "backlog_futuro"
    assert not motor.itens_por_veiculo[vid]
    assert motor.backlog_futuro[0]["motivo"].startswith("Pagamento antecipado")


def test_pendente_posto_a_mao_no_caminhao_nao_duplica_em_parados():
    normal = _linha(2)
    l = _linha(1, data_producao="02/07/26", dias_uteis_antecedencia=9)  # consulta ao representante
    motor = MotorLogistica()
    motor.alocar_frota([normal, l])
    assert _onde(motor, l.id_item) == "backlog_futuro"
    vid = _onde(motor, normal.id_item)
    ok, _ = motor.mover_pedido(l.id_item, vid, forcar=True)  # operador decidiu levar mesmo assim
    assert ok
    motor.sugerir_alocacao([normal, l])
    assert _onde(motor, l.id_item) == vid
    assert not any(b.get("id_item") == l.id_item for b in motor.backlog_futuro)


def test_resolver_pendencia_e_sugerir_coloca_na_rota():
    l = _linha(1, liberacao_comercial="AGUARDANDO")
    motor = MotorLogistica()
    motor.alocar_frota([l])
    assert _onde(motor, l.id_item) == "backlog_futuro"
    l.liberacao_comercial = "LIBERADO"
    alocadas, _ = motor.sugerir_alocacao([l])
    assert alocadas == 1
    assert _onde(motor, l.id_item) not in ("backlog_futuro", "backlog", None)
