"""
Junta, item por item, um arquivo de aprendizado que os DOIS PCs mexeram.

Chamado pelo scripts/sincronizar_dados.bat quando o git acusa conflito:

    python scripts/juntar_json.py <caminho> <base> <nuvem> <este_pc>

- <caminho>: arquivo no projeto (ex.: data/aprendizado_regras.json). Só junta
  os JSON direto em data/ (regras, frases, horários, equipe, mapa, cadastro);
  quadros do dia (data/sessions/...) não: ali vale um quadro inteiro.
- <base>/<nuvem>/<este_pc>: as três versões (antes, outro PC, este PC).

Regra: o que só um PC ensinou/alterou entra; o que só um apagou sai; se os
dois mudaram o MESMO item para valores diferentes, fica o deste PC.
Sai com 0 e grava o resultado em <caminho>; qualquer outro código = não juntou
(o .bat cai no jeito antigo: fica a versão deste PC e a outra vai para
logs/conflitos).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_FALTA = object()
_CHAVES_ID = ("id", "codigo", "chave", "id_item")


def _chave_lista(lista: list[Any]) -> str | None:
    """Lista de registros com identificador comum (ex.: frota por 'id')."""
    if not lista or not all(isinstance(x, dict) for x in lista):
        return None
    for k in _CHAVES_ID:
        valores = [x.get(k) for x in lista]
        if all(v not in (None, "") for v in valores) and len(set(map(str, valores))) == len(valores):
            return k
    return None


def _simples(lista: list[Any]) -> bool:
    return all(not isinstance(x, (dict, list)) for x in lista)


def juntar(base: Any, nuvem: Any, pc: Any) -> Any:
    if nuvem == pc:
        return pc
    if base is not _FALTA and nuvem == base:
        return pc
    if base is not _FALTA and pc == base:
        return nuvem
    if isinstance(nuvem, dict) and isinstance(pc, dict):
        b = base if isinstance(base, dict) else {}
        saida: dict[str, Any] = {}
        ordem = list(pc) + [k for k in nuvem if k not in pc] + [k for k in b if k not in pc and k not in nuvem]
        for k in ordem:
            v = juntar(b.get(k, _FALTA), nuvem.get(k, _FALTA), pc.get(k, _FALTA))
            if v is not _FALTA:
                saida[k] = v
        return saida
    if isinstance(nuvem, list) and isinstance(pc, list):
        b = base if isinstance(base, list) else []
        if _simples(nuvem) and _simples(pc) and _simples(b):
            apagados = [x for x in b if x not in nuvem or x not in pc]
            saida_l = [x for x in pc if x not in apagados or x not in b]
            saida_l += [x for x in nuvem if x not in saida_l and x not in b]
            return saida_l
        k = _chave_lista(nuvem + pc)
        if k is None and _chave_lista(nuvem) and _chave_lista(nuvem) == _chave_lista(pc):
            k = _chave_lista(nuvem)
        if k and all(isinstance(x, dict) and x.get(k) not in (None, "") for x in nuvem + pc + b):
            idx = lambda l: {str(x[k]): x for x in l}  # noqa: E731
            junto = juntar(idx(b), idx(nuvem), idx(pc))
            return list(junto.values())
    # mesmo item mudou dos dois lados (ou um apagou e o outro mudou): fica o deste PC,
    # a não ser que este PC tenha apagado o que o outro alterou
    return nuvem if pc is _FALTA else pc


def _ler(caminho: str) -> Any:
    texto = Path(caminho).read_text(encoding="utf-8-sig").strip()
    return json.loads(texto) if texto else _FALTA


def pode_juntar(caminho: str) -> bool:
    partes = caminho.replace("\\", "/").strip("/").split("/")
    return len(partes) == 2 and partes[0] == "data" and partes[1].lower().endswith(".json")


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        return 2
    _, caminho, f_base, f_nuvem, f_pc = argv
    if not pode_juntar(caminho):
        return 3
    try:
        nuvem, pc = _ler(f_nuvem), _ler(f_pc)
        try:
            base = _ler(f_base)
        except (OSError, ValueError):
            base = _FALTA  # arquivo criado nos dois PCs ao mesmo tempo
        if nuvem is _FALTA or pc is _FALTA:
            return 4  # um lado apagou o arquivo inteiro: não decide sozinho
        resultado = juntar(base, nuvem, pc)
        destino = Path(caminho)
        tmp = destino.with_suffix(destino.suffix + ".juntando")
        tmp.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(destino)
    except (OSError, ValueError):
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
