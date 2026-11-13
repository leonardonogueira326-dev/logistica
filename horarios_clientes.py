"""
Horário de recebimento por cliente (o que não vem escrito na observação).

data/horarios_clientes.json: {"<codigo do cliente>": "08:00 às 17:00"}
Vai junto com os dados (repositório privado), então vale nos dois PCs.

Ordem de confiança na montagem: observação do pedido > horário salvo do
cliente > recebimento padrão (Mesa de Comando).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from normalizador import normalizar_codigo_cliente
from otimizacao import janela_recebimento

RAIZ = Path(__file__).resolve().parent
ARQUIVO = RAIZ / "data" / "horarios_clientes.json"
PADRAO = "08:00 às 17:00"


def carregar(arquivo: Path | None = None) -> dict[str, str]:
    try:
        dados = json.loads((arquivo or ARQUIVO).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in dados.items() if str(v).strip()}
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return {}


def salvar(codigo: str, horario: str, arquivo: Path | None = None) -> None:
    """horario vazio apaga. Levanta ValueError se o texto não tem um horário."""
    arquivo = arquivo or ARQUIVO
    cod = normalizar_codigo_cliente(codigo)
    if not cod:
        raise ValueError("Cliente sem código.")
    dados = carregar(arquivo)
    if horario.strip():
        if not janela_recebimento(horario):
            raise ValueError('Não entendi o horário. Use, por exemplo, "08:00 às 17:00".')
        dados[cod] = horario.strip()
    else:
        dados.pop(cod, None)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def janela_da_parada(
    linha: dict[str, Any], memoria: dict[str, str], padrao: str = PADRAO
) -> tuple[Optional[tuple[int, int]], str]:
    """(janela em minutos, de onde veio: observacao | cliente | padrao)."""
    da_obs = janela_recebimento(str(linha.get("obs_recebimento") or ""))
    if da_obs:
        return da_obs, "observacao"
    salvo = memoria.get(normalizar_codigo_cliente(str(linha.get("cliente_codigo") or "")))
    if salvo and janela_recebimento(salvo):
        return janela_recebimento(salvo), "cliente"
    return janela_recebimento(padrao or PADRAO), "padrao"
