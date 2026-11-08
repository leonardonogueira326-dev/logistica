"""Geocodificação com cache/correção manual e sequência de entrega (OR-Tools)."""

import pytest

import geocodificacao as geo
from otimizacao import janela_recebimento, km, otimizar


@pytest.fixture
def cache_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(geo, "ARQUIVO_CACHE", tmp_path / "geocache.json")
    monkeypatch.setattr(geo, "enderecos_base", lambda: {
        "3144": {"endereco": "RUA A", "bairro": "BRAS", "cidade": "SAO PAULO", "cep": "03001-000"},
        "5143": {"endereco": "RUA B", "bairro": "", "cidade": "PINHALZINHO", "cep": "89870-000"},
    })
    return tmp_path


def _buscador(respostas):
    chamadas = []

    def buscar(params):
        chamadas.append(params)
        for chave, coord in respostas.items():
            if chave in params.values():
                return coord
        return None

    return buscar, chamadas


def test_cliente_na_cidade_do_cadastro_usa_endereco_e_fica_no_cache(cache_tmp):
    buscar, chamadas = _buscador({"RUA A": (-23.55, -46.63)})
    linha = {"cliente_codigo": "03144", "cidade_destino": "SAO PAULO", "estado_destino": "SAO PAULO"}
    r = geo.geocodificar_linhas([linha], buscar=buscar)
    assert r["feitos"] == 1 and not r["nao_achados"]
    ponto = geo.coordenada_da_linha(linha)
    assert (ponto["lat"], ponto["precisao"]) == (-23.55, "endereco")
    geo.geocodificar_linhas([linha], buscar=buscar)  # segunda vez: não consulta de novo
    assert len(chamadas) == 1


def test_redespacho_usa_a_cidade_de_destino_do_pdf(cache_tmp):
    buscar, _ = _buscador({"GUARULHOS": (-23.46, -46.53)})
    linha = {"cliente_codigo": "05143", "cidade_destino": "GUARULHOS", "estado_destino": "SAO PAULO"}
    assert geo.chave_da_linha(linha).startswith("CID:GUARULHOS")
    geo.geocodificar_linhas([linha], buscar=buscar)
    assert geo.coordenada_da_linha(linha)["precisao"] == "cidade"


def test_cai_para_cep_e_depois_cidade(cache_tmp):
    chamadas = []

    def buscar(params):  # rua não encontrada; só o CEP responde
        chamadas.append(params)
        return (-23.54, -46.62) if params.get("postalcode") and not params.get("street") else None

    linha = {"cliente_codigo": "03144", "cidade_destino": "SAO PAULO"}
    geo.geocodificar_linhas([linha], buscar=buscar)
    assert geo.coordenada_da_linha(linha)["precisao"] == "cep"
    assert len(chamadas) == 2


def test_correcao_manual_vale_para_frente(cache_tmp):
    buscar, _ = _buscador({"RUA A": (-23.55, -46.63)})
    linha = {"cliente_codigo": "03144", "cidade_destino": "SAO PAULO"}
    geo.geocodificar_linhas([linha], buscar=buscar)
    geo.definir_manual(geo.chave_da_linha(linha), -23.50, -46.60)
    geo.geocodificar_linhas([linha], buscar=buscar)
    ponto = geo.coordenada_da_linha(linha)
    assert ponto["manual"] and ponto["lat"] == -23.50


def test_sem_internet_para_e_avisa(cache_tmp):
    def offline(_):
        raise ConnectionError("Serviço de mapas indisponível")

    r = geo.geocodificar_linhas([{"cliente_codigo": "03144", "cidade_destino": "SAO PAULO"}], buscar=offline)
    assert "indisponível" in r["erro"]


@pytest.mark.parametrize(
    "texto, janela",
    [
        ("RECEBIMENTO: Seg a quin. das 08:30h até as 11:30h", (510, 690)),
        ("Horário de recebimento: Seg a Sex das 7:30 as 11:45", (450, 705)),
        ("SÓ ABRE AS 8:00", (480, 1080)),
        ("RECEBIMENTO DAS 8 ÀS 15 HORAS", (480, 900)),
        ("", None),
    ],
)
def test_janela_de_recebimento(texto, janela):
    assert janela_recebimento(texto) == janela


SBO = (-22.7536, -47.4136)


def test_otimizar_reduz_distancia_em_ida_e_volta_bagunçada():
    # Ordem atual ruim: vai longe, volta perto, vai longe de novo
    paradas = [
        {"id": "ATIBAIA", "lat": -23.12, "lon": -46.55, "janela": None},
        {"id": "SUMARE", "lat": -22.82, "lon": -47.27, "janela": None},
        {"id": "GUARULHOS", "lat": -23.46, "lon": -46.53, "janela": None},
        {"id": "AMERICANA", "lat": -22.74, "lon": -47.33, "janela": None},
    ]
    r = otimizar(paradas, SBO)
    assert r["km_depois"] < r["km_antes"]
    assert sorted(r["ordem"]) == sorted(p["id"] for p in paradas)


def test_otimizar_respeita_janela_quando_possivel():
    paradas = [
        {"id": "PERTO_TARDE", "lat": -22.74, "lon": -47.33, "janela": (14 * 60, 17 * 60)},
        {"id": "LONGE_MANHA", "lat": -23.46, "lon": -46.53, "janela": (8 * 60, 11 * 60)},
    ]
    r = otimizar(paradas, SBO, inicio_min=6 * 60)
    assert r["ordem"] == ["LONGE_MANHA", "PERTO_TARDE"]
    assert not r["aviso"]


def test_parada_sem_coordenada_fica_no_fim_com_aviso():
    paradas = [
        {"id": "SEM", "lat": None, "lon": None},
        {"id": "A", "lat": -22.74, "lon": -47.33},
        {"id": "B", "lat": -22.82, "lon": -47.27},
    ]
    r = otimizar(paradas, SBO)
    assert r["ordem"][-1] == "SEM" and "sem localização" in r["aviso"]


def test_km_aproximado():
    assert 100 < km(SBO, (-23.55, -46.63)) < 200  # SBO -> São Paulo
