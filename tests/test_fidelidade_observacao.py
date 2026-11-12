"""
Fidelidade da observação: para cada linha dos PDFs de teste, a observação lida
pelo sistema tem que ser igual às palavras da coluna Observação recortadas do
PDF na faixa daquela mesma linha (método independente do extrator).
Garante que observação de uma linha não vaza para outra.
"""
from __future__ import annotations

import collections
import glob
import re
import unicodedata

import pytest

from extrator_pdf import ExtratorPDF

PDFS = sorted(glob.glob("dados_teste/*.pdf"))
RE_PED = re.compile(r"^\d{6}/\d{2}/\d{3}$")


def _palavras(t: str) -> collections.Counter:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().upper()
    return collections.Counter(re.findall(r"[A-Z0-9]+", t))


@pytest.mark.skipif(not PDFS, reason="sem PDFs de teste (ficam no repositório privado de dados)")
@pytest.mark.parametrize("pdf", PDFS)
def test_observacao_de_cada_linha_e_a_da_propria_linha(pdf):
    import pdfplumber

    lidas = {p.numero_pedido: p.observacao_comercial for p in ExtratorPDF(pdf).extrair()}
    diferentes = []
    with pdfplumber.open(pdf) as doc:
        for pg in doc.pages:
            ws = pg.extract_words(extra_attrs=["size"])
            cab = [w for w in ws if w["text"].startswith("Observa") and w["x0"] > pg.width * 0.4]
            if not cab:
                continue
            x_obs = cab[0]["x0"] - 4
            linhas = sorted((w for w in ws if RE_PED.match(w["text"]) and w["x0"] < 150), key=lambda w: w["top"])
            fim = max(w["bottom"] for w in ws) + 1
            for i, ln in enumerate(linhas):
                topo, base = ln["top"] - 1, (linhas[i + 1]["top"] - 1 if i + 1 < len(linhas) else fim)
                faixa = sorted(
                    (w for w in ws if topo <= w["top"] < base and w["x0"] >= x_obs and float(w["size"]) >= 7.5),
                    key=lambda w: (round(w["top"]), w["x0"]),
                )
                texto = []
                for w in faixa:
                    if w["text"].startswith(("Representante:", "Destino:", "Transp:", "Qtde.")):
                        break
                    texto.append(w["text"])
                esperado, lido = _palavras(" ".join(texto)), _palavras(lidas.get(ln["text"], ""))
                uniao = sum((esperado | lido).values())
                if uniao and sum((esperado & lido).values()) / uniao < 0.98:
                    diferentes.append(ln["text"])
    assert not diferentes, f"observação diferente do PDF em: {diferentes}"
