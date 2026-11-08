"""
Testes com PDFs reais de faturamento.

Os PDFs NÃO vão para o GitHub (dados de clientes). Coloque-os na pasta
`dados_teste/` na raiz do projeto para rodar estes testes; sem eles, são pulados.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from extrator_pdf import ExtratorPDF

PASTA = Path(__file__).resolve().parent.parent / "dados_teste"
PDFS = sorted(PASTA.glob("*.pdf")) if PASTA.exists() else []

pytestmark = pytest.mark.skipif(not PDFS, reason="sem PDFs em dados_teste/")


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.name)
def test_extrai_todos_os_pedidos_sem_erro(pdf):
    ext = ExtratorPDF(str(pdf))
    pedidos = ext.extrair()
    assert pedidos, "nenhum pedido extraído"
    assert not ext.erros, ext.erros
    assert any("colunas" in a for a in ext.avisos), "modo por colunas não foi usado"


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.name)
def test_campos_essenciais_preenchidos(pdf):
    pedidos = ExtratorPDF(str(pdf)).extrair()
    for p in pedidos:
        assert p.cliente_codigo, p.numero_pedido
        assert p.cidade_destino, f"{p.numero_pedido} sem destino"
        assert p.data_producao, f"{p.numero_pedido} sem data"


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.name)
def test_observacao_nao_vaza_para_nome_do_cliente(pdf):
    proibidas = ("PAGAMENTO", "PAGTO", "REMESSA", "DECRETO", "ENTREGAR", "BOLETO")
    for p in ExtratorPDF(str(pdf)).extrair():
        nome = p.cliente_nome.upper()
        assert not any(w in nome for w in proibidas), f"{p.numero_pedido}: {p.cliente_nome}"


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.name)
def test_toda_linha_tem_of_valida_e_diferente_do_pedido(pdf):
    import re

    for p in ExtratorPDF(str(pdf)).extrair():
        assert re.fullmatch(r"\d{6}/\d{2}", p.of_ano), f"{p.numero_pedido}: OF '{p.of_ano}'"
        # bug antigo: a OF era lida do próprio número do pedido (003060/26/002 -> 003060/26)
        assert not p.numero_pedido.startswith(p.of_ano + "/"), p.numero_pedido


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.name)
def test_pedido_item_of_identifica_cada_linha(pdf):
    pedidos = ExtratorPDF(str(pdf)).extrair()
    chaves = [(p.numero_pedido, p.of_ano) for p in pedidos]
    assert len(chaves) == len(set(chaves)), "pedido+item+OF repetido no mesmo PDF"
