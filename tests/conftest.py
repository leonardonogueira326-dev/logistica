from __future__ import annotations
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import os

# Testes não consultam o serviço de mapas sozinhos (localização automática do quadro)
os.environ.setdefault("LOGISTICA_SEM_GEO_AUTO", "1")

# Testes usam arquivos soltos; o banco local tem testes próprios (test_armazenamento.py)
os.environ.setdefault("LOGISTICA_SEM_BANCO", "1")


def trocar_no_quadro(monkeypatch, nome: str, valor) -> None:
    """Troca um nome em todos os módulos do quadro que o usam (rotas + regras)."""
    import api.routers.quadro_mapa as mapa
    import api.routers.quadro_montagem as montagem
    import api.routers.sessions as sessoes
    import api.servicos.quadro as servico

    achou = False
    for modulo in (servico, sessoes, mapa, montagem):
        if hasattr(modulo, nome):
            monkeypatch.setattr(modulo, nome, valor)
            achou = True
    assert achou, f"{nome} não existe em nenhum módulo do quadro"
