"""
Catálogo de pegadinhas das observações comerciais.

Cada caso é uma frase real (ou quase) vista nos PDFs de faturamento e o que
o sistema deve concluir. Ao encontrar uma pegadinha nova: adicione aqui.
"""

import pytest

from extrator_pdf import observacao_apenas_administrativa, remover_texto_padrao
from quarentena import avaliar_quarentena, detectar_alertas_comerciais

DECRETO = "Redução do DECRETO Nº 11.055, DE 28 DE ABRIL DE 2022"


@pytest.mark.parametrize(
    "observacao, motivo_esperado",
    [
        (f"{DECRETO} - NAO ULTRAPASSAR PESO PAGAMENTO ANTECIPADO", "Pagamento antecipado"),
        ("PAGTO. ANTECIPADO DEPOSITO QUANDO MATERIAL ESTIVER PRONTO", "Pagamento antecipado"),
        (f"{DECRETO} - NÃO FATURAR E EMBARCAR ANTES DA DATA", "Restrição de data"),
        ("ITENS DEVEM SER FATURADOS A PARTIR DE 25.06 ANTES NÃO", "Restrição de data"),
        ("OBEDECER DATAS DOS PEDIDOS ( SÓ PODEMOS FATURAR", "Restrição de data"),
        ("NÃO ENVIAR PARCIAL - TRANSPORTADORA COLETA NA FABRICA", "parcial"),
        ("FATURAR SEMPRE TOTAL OU PARCIAL COM AUTORIZALÇÃO COMERCIAL", "parcial"),
        ("NÃO ACEITAM NFS EMITIDAS APÓS DIA 22 DO MÊS", "fim do mês"),
        ("Cliente não aceitara notas fiscais emitidas no final do mês", "fim do mês"),
        ("CLIENTE NÃO RECEBE MATERIAIS FATURADOS EM UM MÊS E ENTREGUE NO PROXIMO", "fim do mês"),
    ],
)
def test_alerta_comercial_detectado(observacao, motivo_esperado):
    motivos = detectar_alertas_comerciais(observacao)
    assert any(motivo_esperado.lower() in m.lower() for m in motivos), motivos


@pytest.mark.parametrize(
    "observacao",
    [
        DECRETO,
        f"ENVIAR BOLETOS POR E-MAIL fulano@empresa.com.br {DECRETO}",
        "ICMS DE 12% AUTORIZADO PELA DIRETORIA",
    ],
)
def test_sem_alerta_comercial(observacao):
    assert detectar_alertas_comerciais(observacao) == []


def test_texto_padrao_do_decreto_e_removido():
    obs = f"{DECRETO} - NAO ULTRAPASSAR PESO PAGAMENTO ANTECIPADO"
    assert remover_texto_padrao(obs) == "NAO ULTRAPASSAR PESO PAGAMENTO ANTECIPADO"


def test_decreto_nao_torna_observacao_administrativa():
    # Antes: "DECRETO" fazia a observação inteira ser tratada como administrativa.
    obs = f"{DECRETO} - LEVAR NA TRANSPORTADORA"
    assert observacao_apenas_administrativa(obs) is False


def test_peso_zerado_vai_para_conferencia():
    revisao, motivo, _ = avaliar_quarentena(0.0, "REMESSA PARA INDUSTRIALIZAÇÃO")
    assert revisao == "REVISAO_OBRIGATORIA"
    assert "Peso Zerado" in motivo


def test_regra_aprendida_dispensa_conferencia():
    revisao, _, _ = avaliar_quarentena(0.0, "PAGAMENTO ANTECIPADO", aprendizado_aplicado="SIM")
    assert revisao == "NAO"
