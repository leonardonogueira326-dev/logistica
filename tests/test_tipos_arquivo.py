"""Garante que o servidor entrega .js/.css com o tipo certo (bug do registro do Windows)."""
from __future__ import annotations
import mimetypes

import api.main  # noqa: F401  (registra os tipos)


def test_js_e_css_com_tipo_correto():
    mimetypes.add_type("text/plain", ".js")  # simula o registro do Windows
    import importlib
    importlib.reload(api.main)
    assert mimetypes.guess_type("a.js")[0] == "application/javascript"
    assert mimetypes.guess_type("a.css")[0] == "text/css"
