"""Montagem de cargas: desfazer, ordem otimizada que expira, nomes sem ambiguidade, equipe."""
from __future__ import annotations

from api.session_store import SessionStore
from models import ItemRota, RotaVeiculo
from motor_logistica import MotorLogistica


def test_desfazer_volta_uma_versao_por_vez(tmp_path):
    store = SessionStore(tmp_path / "data" / "sessions")
    sid = store.create_session()
    store.save_roteirizacao(sid, {"v": 1})
    store.save_roteirizacao(sid, {"v": 2})
    store.save_roteirizacao(sid, {"v": 2})  # igual: não empilha
    store.save_roteirizacao(sid, {"v": 3})
    assert store.qtd_desfazer(sid) == 2
    assert store.desfazer_roteirizacao(sid) == {"v": 2}
    assert store.load_roteirizacao(sid) == {"v": 2}
    assert store.desfazer_roteirizacao(sid) == {"v": 1}
    assert store.desfazer_roteirizacao(sid) is None
    # a pilha fica fora da pasta de dados sincronizada
    assert (tmp_path / ".desfazer" / f"{sid}.json").is_file()
    assert not list((tmp_path / "data").rglob("*desfazer*"))


def _item(cliente: str, codigo: str, peso: float, cep: str = "") -> ItemRota:
    return ItemRota(numero_pedido=f"P{codigo}", id_item=f"P{codigo}#1", cliente=cliente, cliente_codigo=codigo,
                    cidade_destino="SAO PAULO", cep_destino=cep, peso_kg=peso)


def _motor() -> MotorLogistica:
    m = MotorLogistica(params={"corredores_logisticos": {}})
    m.rotas = [RotaVeiculo(veiculo_id="11.180_BAU_1", veiculo_nome="11.180 - BAÚ", capacidade_kg=6000),
               RotaVeiculo(veiculo_id="11.180_BAU_2", veiculo_nome="11.180 - BAÚ", capacidade_kg=6100)]
    m.itens_por_veiculo = {"11.180_BAU_1": [_item("A", "1", 100), _item("B", "2", 200)], "11.180_BAU_2": []}
    return m


def test_ordem_otimizada_expira_quando_a_carga_muda():
    m = _motor()
    assert not m.ordem_otimizada("11.180_BAU_1")
    m.sequencia_otimizada["11.180_BAU_1"] = m.assinatura_carga("11.180_BAU_1")
    assert m.ordem_otimizada("11.180_BAU_1")
    m.itens_por_veiculo["11.180_BAU_1"].reverse()  # mexeu na ordem
    assert not m.ordem_otimizada("11.180_BAU_1")
    assert m.ordem_otimizada("11.180_BAU_2")  # vazio: nada a otimizar


def test_caminhoes_de_mesmo_nome_ganham_numero():
    from api.servicos.quadro import _nomes_veiculos

    assert _nomes_veiculos(_motor()) == {"11.180_BAU_1": "11.180 - BAÚ · 1", "11.180_BAU_2": "11.180 - BAÚ · 2"}


def test_sugestao_de_corredor_aponta_o_caminhao_certo():
    m = _motor()
    m.params["corredores_logisticos"] = {"1": {"nome": "Sul/ABC"}, "2": {"nome": "Norte/Marginal"}}
    m._cache_mapa_corredor = {"09": 1, "02": 2}  # prefixo do CEP -> corredor
    m._prefixo_cep = lambda cep: str(cep)[:2]  # type: ignore[method-assign]
    m.itens_por_veiculo = {
        "11.180_BAU_1": [_item("NICROSOL (NICROSOL)", "1", 900, "09000"), _item("HAENKE (HAENKE)", "2", 800, "09100"),
                         _item("DECKTEL IND (DECKTEL)", "3", 300, "02000")],
        "11.180_BAU_2": [_item("LCS (LCS)", "4", 100, "02100")],
    }
    m.rotas[1].peso_alocado_kg = 100
    sug = m.sugestao_corredor("11.180_BAU_1", {"11.180_BAU_2": "11.180 - BAÚ · 2"})
    assert sug == {"texto": "Sugestão: passar DECKTEL para 11.180 - BAÚ · 2", "ids": ["P3#1"], "destino": "11.180_BAU_2"}


def test_nomes_da_equipe_ficam_guardados(tmp_path, monkeypatch):
    import equipe

    monkeypatch.setattr(equipe, "ARQUIVO_NOMES", tmp_path / "nomes.json")
    monkeypatch.setattr(equipe, "carregar_padrao", lambda: {"V1": {"motorista": "Joao", "ajudante": ""}})
    monkeypatch.setattr(equipe, "frota_cadastrada", lambda: [{"id": "V1", "placa": "abc1d23"}])
    equipe.guardar_nomes({"motorista": "carlos", "ajudante": "pedro", "placa": "XYZ9A99"})
    nomes = equipe.nomes_conhecidos()
    assert nomes == {"motoristas": ["CARLOS", "JOAO"], "ajudantes": ["PEDRO"], "placas": ["ABC1D23", "XYZ9A99"]}
