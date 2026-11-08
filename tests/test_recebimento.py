import pytest

from recebimento import extrair_restricao_recebimento as extrair


@pytest.mark.parametrize(
    "obs, esperado",
    [
        ("BOFER - SÓ ABRE AS 8:00", "SÓ ABRE AS 8:00"),
        (
            "PAGAMENTO SOMENTE NOS DIAS 05, 10 - RECEBIMENTO: Seg a quin. das 08:30h até as 11:30h",
            "RECEBIMENTO: Seg a quin. das 08:30h até as 11:30h",
        ),
        (  # erro de digitação no PDF real (LCS)
            "PAGAMENTO SOMENTE NOS DIAS 10 - Recdebimento: seg. a quinta-feira das 08:30h á 11:30h ENVIAR BOLETO",
            "Recdebimento: seg. a quinta-feira das 08:30h á 11:30h",
        ),
        (
            "Horário de recebimento: Seg a Sex das 7:30 as 11:45 horas Envio de boletos Nicrosol",
            "Horário de recebimento: Seg a Sex das 7:30 as 11:45 horas",
        ),
        ("ENVIAR BOLETOS PARA fulano@empresa.com.br - Redução do DECRETO Nº 11.055, DE 28 DE ABRIL DE 2022", ""),
        ("PAGAMENTO SOMENTE NOS DIAS 10, 15 e 30", ""),
    ],
)
def test_restricao_de_recebimento(obs, esperado):
    assert extrair(obs) == esperado
