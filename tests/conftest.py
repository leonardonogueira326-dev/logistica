from __future__ import annotations
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import os

# Testes não consultam o serviço de mapas sozinhos (localização automática do quadro)
os.environ.setdefault("LOGISTICA_SEM_GEO_AUTO", "1")
