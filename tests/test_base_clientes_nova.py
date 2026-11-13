"""Base de clientes exportada pelo sistema da empresa (aba Dados, com endereço e número)."""
from __future__ import annotations

from pathlib import Path

import openpyxl

import geocodificacao as g
from extrator_clientes import _lookup_planilha_dados

CAB = ("CODIGO", "RAZAO_SOCIAL", "NOME_FANTASIA", "CPF_CNPJ", "ENDERECO", "NUMERO", "BAIRRO", "COMPLEMENTO",
       "CIDADE", "UF", "CEP", "TELEFONE", "EMAIL", "CODIGO_REPRESENTANTE", "REPRESENTANTE_RAZAO",
       "REPRESENTANTE_FANTASIA", "STATUS", "LIMITE_CLIENTE", "ULTIMA_VENDA")


def _base(tmp_path: Path, linhas) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Dados"
    ws.append(CAB)
    for l in linhas:
        ws.append(l)
    caminho = tmp_path / "base-de-clientes.xlsx"
    wb.save(caminho)
    return caminho


LINHA = (5848, "RP MOLAS IND E COM", "RP MOLAS", "x", "ITANHAEM", "1902", "JD PAULISTA", None, "RIBEIRAO PRETO ",
         "SP", "14075-050", "(16)3333-0000", "a@b", 2797, "THIARA CAROLINE", "THIARA - CERCA", "Ativo    ", None, None)


def test_lookup_traz_endereco_com_numero(tmp_path):
    l = _lookup_planilha_dados(_base(tmp_path, [LINHA]))["5848"]
    assert l["endereco"] == "ITANHAEM, 1902" and l["bairro"] == "JD PAULISTA"
    assert l["cidade"] == "RIBEIRAO PRETO" and l["cep"] == "14075-050"
    assert l["representante"] == "THIARA - CERCA" and l["status_cliente"] == "ATIVO"


def test_geocodificacao_le_a_base_nova_e_a_antiga_completa(tmp_path, monkeypatch):
    _base(tmp_path, [LINHA, (1, "A", "A", "", None, None, None, None, "SAO PAULO", "SP", None, *([None] * 8))])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(("Código", "Razão Social", "Endereço", "Bairro", "Cidade", "CEP"))
    ws.append((1, "A", "RUA VELHA", "CENTRO", "SAO PAULO", "01000-000"))
    wb.save(tmp_path / "base-de-clientes1.xlsx")
    monkeypatch.setattr(g, "RAIZ", tmp_path)
    g._cache_base.clear()
    base = g.enderecos_base()
    assert base["5848"]["endereco"] == "ITANHAEM, 1902" and base["5848"]["uf"] == "SP"
    assert base["1"]["endereco"] == "RUA VELHA" and base["1"]["cep"] == "01000-000"
    g._cache_base.clear()


def test_refaz_o_mapa_quando_a_base_ganha_o_numero():
    end = {"endereco": "ITANHAEM, 1902"}
    assert g.precisa_refazer({"precisao": "cep", "consulta": "14075-050"}, end)
    assert g.precisa_refazer({"precisao": "endereco", "consulta": "ITANHAEM, RIBEIRAO PRETO"}, end)
    assert not g.precisa_refazer({"precisao": "endereco", "consulta": "ITANHAEM, 1902, RIBEIRAO PRETO"}, end)
    assert not g.precisa_refazer({"precisao": "cep", "base_endereco": "ITANHAEM, 1902"}, end)  # já tentou
    assert not g.precisa_refazer({"precisao": "cidade", "manual": True}, end)
    assert not g.precisa_refazer({"precisao": "cep"}, {"endereco": "ITANHAEM"})  # sem número


def test_geocodificar_linhas_refaz_e_nao_repete(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "ARQUIVO_CACHE", tmp_path / "geocache.json")
    monkeypatch.setattr(g, "enderecos_base", lambda: {"5848": {"endereco": "ITANHAEM, 1902", "cidade": "RIBEIRAO PRETO",
                                                              "uf": "SP", "cep": "14075-050"}})
    g.salvar_cache({"CLI:5848": {"lat": 1.0, "lon": 1.0, "precisao": "cep", "consulta": "14075-050"}})
    chamadas = []

    def buscar(params):
        chamadas.append(params)
        return (-21.2, -47.8) if params.get("street") == "ITANHAEM, 1902" else None

    linha = {"cliente_codigo": "05848", "cidade_destino": "RIBEIRAO PRETO", "tipo_frete": "ENTREGA_DIRETA"}
    g.geocodificar_linhas([linha], buscar)
    novo = g.carregar_cache()["CLI:5848"]
    assert novo["precisao"] == "endereco" and novo["lat"] == -21.2
    n = len(chamadas)
    g.geocodificar_linhas([linha], buscar)
    assert len(chamadas) == n  # não consulta de novo
