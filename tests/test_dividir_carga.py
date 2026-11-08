"""
Divisão de uma linha entre caminhões, só por peso.

Ex.: pedido de 10 t e caminhões de no máximo ~6 t -> a linha vira 2 cargas.
Materiais: rolo, SPYDER, barras de até 6 m, carretéis — a divisão é por kg.
"""

from models import PedidoConsolidado
from motor_logistica import MotorLogistica


def _linha(peso: float, of: str = "005037/26", **extra) -> PedidoConsolidado:
    base = dict(
        numero_pedido="003060/26/001",
        id_item=f"003060/26/001#{of}",
        of_ano=of,
        cliente="CLIENTE GRANDE",
        cliente_codigo="09999",
        peso_kg=peso,
        cidade_destino="SAO PAULO",
        estado_destino="SAO PAULO",
        status="LIBERADO",
    )
    base.update(extra)
    return PedidoConsolidado(**base)


def _cargas(motor: MotorLogistica, id_item: str):
    """(coluna, id_carga, peso, parte) de todas as cargas da linha."""
    out = []
    for vid, itens in motor.itens_por_veiculo.items():
        out += [(vid, i.id_carga, i.peso_kg, i.parte) for i in itens if i.id_item == id_item]
    for nome in ("backlog", "backlog_local"):
        out += [
            (nome, b["id_carga"], float(b["peso_kg"]), b.get("parte", ""))
            for b in getattr(motor, nome) if b.get("id_item") == id_item
        ]
    return out


def _cap_max(motor: MotorLogistica) -> float:
    return max(float(v.get("capacidade_peso", 0)) for _, v in motor._ordem_veiculos(False))


def test_linha_maior_que_qualquer_caminhao_e_dividida_automaticamente():
    motor = MotorLogistica()
    cap = _cap_max(motor)
    peso = round(cap * 1.6)  # não cabe em nenhum caminhão
    motor.alocar_frota([_linha(peso)])

    cargas = _cargas(motor, "003060/26/001#005037/26")
    assert len(cargas) == 2, cargas
    assert abs(sum(c[2] for c in cargas) - peso) < 0.01, "peso total não pode mudar"
    assert all(c[2] <= cap for c in cargas)
    assert {c[3] for c in cargas} == {"1/2", "2/2"}
    assert len({c[1] for c in cargas}) == 2, "cada parte tem id próprio"


def test_linha_que_cabe_nao_e_dividida():
    motor = MotorLogistica()
    motor.alocar_frota([_linha(500)])
    cargas = _cargas(motor, "003060/26/001#005037/26")
    assert len(cargas) == 1 and cargas[0][3] == ""


def test_divisao_respeita_limite_do_syder_para_barra_longa():
    motor = MotorLogistica()
    caps_syder = [
        float(v.get("capacidade_peso", 0)) for _, v in motor._ordem_veiculos(False) if v.get("tipo") == "SYDER"
    ]
    if not caps_syder:
        return  # sem SYDER disponível na configuração
    cap = max(caps_syder)
    motor.alocar_frota([_linha(cap + 500, is_dimensao_longa="SIM", exige_syder="SIM")])
    cargas = _cargas(motor, "003060/26/001#005037/26")
    assert len(cargas) == 2
    assert all(c[2] <= cap for c in cargas)


def test_dividir_manual_mantem_peso_e_cria_parte_na_mesma_coluna():
    motor = MotorLogistica()
    motor.alocar_frota([_linha(1000)])
    (coluna, id_carga, peso, _), = _cargas(motor, "003060/26/001#005037/26")

    ok, msg = motor.dividir_carga(id_carga, 300)
    assert ok, msg
    cargas = _cargas(motor, "003060/26/001#005037/26")
    assert sorted(c[2] for c in cargas) == [300, 700]
    assert {c[0] for c in cargas} == {coluna}
    assert {c[3] for c in cargas} == {"1/2", "2/2"}

    # dividir de novo -> 3 partes, peso total preservado
    alvo = next(c for c in cargas if c[2] == 700)
    ok, _ = motor.dividir_carga(alvo[1], 200)
    assert ok
    cargas = _cargas(motor, "003060/26/001#005037/26")
    assert sorted(c[2] for c in cargas) == [200, 300, 500]
    assert {c[3] for c in cargas} == {"1/3", "2/3", "3/3"}


def test_parte_dividida_pode_ir_para_outra_coluna_sozinha():
    motor = MotorLogistica()
    motor.alocar_frota([_linha(1000)])
    (_, id_carga, _, _), = _cargas(motor, "003060/26/001#005037/26")
    motor.dividir_carga(id_carga, 400)
    nova = next(c for c in _cargas(motor, "003060/26/001#005037/26") if c[2] == 400)

    ok, _ = motor.mover_pedido(nova[1], "BACKLOG", motivo="vai amanhã")
    assert ok
    por_coluna = {c[0]: c[2] for c in _cargas(motor, "003060/26/001#005037/26")}
    assert por_coluna.get("backlog") == 400
    assert 600 in por_coluna.values()


def test_dividir_peso_invalido_recusa():
    motor = MotorLogistica()
    motor.alocar_frota([_linha(1000)])
    (_, id_carga, _, _), = _cargas(motor, "003060/26/001#005037/26")
    assert motor.dividir_carga(id_carga, 1000)[0] is False
    assert motor.dividir_carga(id_carga, 0)[0] is False


# --- O operador decide: divisão automática é sugestão + ajuste fino -------------

ID = "003060/26/001#005037/26"


def _auto_10t():
    motor = MotorLogistica()
    peso = round(_cap_max(motor) * 1.6)
    motor.alocar_frota([_linha(peso)])
    return motor, peso


def test_divisao_automatica_fica_pendente_de_conferencia():
    motor, _ = _auto_10t()
    flags = [
        i.divisao_automatica
        for itens in motor.itens_por_veiculo.values() for i in itens if i.id_item == ID
    ] + [b.get("divisao_automatica") for b in motor.backlog if b.get("id_item") == ID]
    assert flags and all(f == "SIM" for f in flags)


def test_ajuste_fino_5322_kg_e_o_restante_vai_para_a_outra_parte():
    motor, peso = _auto_10t()
    p1 = next(c for c in _cargas(motor, ID) if c[3] == "1/2")

    ok, msg = motor.ajustar_divisao(p1[1], 5322)
    assert ok, msg
    pesos = {c[1]: c[2] for c in _cargas(motor, ID)}
    assert pesos[p1[1]] == 5322
    assert abs(sum(pesos.values()) - peso) < 0.01
    assert len(pesos) == 2
    # ajustar = operador conferiu
    assert not any(
        i.divisao_automatica for itens in motor.itens_por_veiculo.values() for i in itens if i.id_item == ID
    )


def test_ajuste_que_zera_a_outra_parte_absorve_ela():
    motor = MotorLogistica()
    motor.alocar_frota([_linha(1000)])
    (_, cid, _, _), = _cargas(motor, ID)
    motor.dividir_carga(cid, 300)
    grande = next(c for c in _cargas(motor, ID) if c[2] == 700)
    ok, msg = motor.ajustar_divisao(grande[1], 1000)
    assert ok, msg
    assert [c[2] for c in _cargas(motor, ID)] == [1000]


def test_ajuste_acima_do_total_e_recusado():
    motor = MotorLogistica()
    motor.alocar_frota([_linha(1000)])
    (_, cid, _, _), = _cargas(motor, ID)
    motor.dividir_carga(cid, 300)
    p = _cargas(motor, ID)[0]
    assert motor.ajustar_divisao(p[1], 1500)[0] is False


def test_ajuste_avisa_quando_estoura_capacidade():
    motor, peso = _auto_10t()
    p1 = next(c for c in _cargas(motor, ID) if c[3] == "1/2")
    cap = next(r.capacidade_kg for r in motor.rotas if r.veiculo_id == p1[0])
    ok, msg = motor.ajustar_divisao(p1[1], min(cap + 500, peso - 1))
    assert ok
    assert "ATENÇÃO" in msg and "capacidade" in msg


def test_juntar_partes_desfaz_a_divisao():
    motor, peso = _auto_10t()
    p1 = _cargas(motor, ID)[0]
    ok, _ = motor.juntar_partes(p1[1])
    assert ok
    cargas = _cargas(motor, ID)
    assert len(cargas) == 1
    coluna, id_carga, peso_final, parte = cargas[0]
    assert peso_final == peso and parte == "" and id_carga == ID


def test_confirmar_divisao_limpa_o_aviso():
    motor, _ = _auto_10t()
    p1 = _cargas(motor, ID)[0]
    assert motor.confirmar_divisao(p1[1])[0]
    assert not any(
        i.divisao_automatica for itens in motor.itens_por_veiculo.values() for i in itens if i.id_item == ID
    )
