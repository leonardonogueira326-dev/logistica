"""Retira / coleta: por que o sistema decidiu, e conferência que ensina."""
from __future__ import annotations

from conferencia_frete import evidencia, lembrar


def _c(**k):
    base = dict(status="TERCEIRO", cliente_codigo="05813", transportadora_codigo="00865",
                transportadora="EXPRESSO SAO MIGUEL - SUMARE - R. SERGIO", observacao_comercial="")
    base.update(k)
    return base


def test_frase_na_observacao_e_verde():
    t, n = evidencia(_c(observacao_comercial="TRANSPORTADORA COLETA - Redução do DECRETO Nº 11.055, DE 28 DE ABRIL DE 2022"), {})
    assert n == "VERDE" and "COLETA" in t


def test_sem_frase_e_vermelho_e_conferir_ensina(tmp_path):
    arq = tmp_path / "conf.json"
    linha = _c(observacao_comercial="Redução do DECRETO Nº 11.055, DE 28 DE ABRIL DE 2022")
    t, n = evidencia(linha, {})
    assert n == "VERMELHO" and "EXPRESSO SAO MIGUEL" in t
    assert lembrar([linha], arq) == 1
    import json
    t, n = evidencia(linha, json.loads(arq.read_text()))
    assert n == "VERDE" and "Já conferido" in t


def test_frota_propria_nao_entra():
    assert evidencia(_c(status="LIBERADO"), {}) == ("", "")
