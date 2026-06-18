"""
Ponto de entrada da Fase 1 — Motor de Ingestão Superfine.

Uso:
    python main_ingestao.py
    python main_ingestao.py --pasta "c:\\Users\\Usuario\\Desktop\\logistica"
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from gerador_debug import gerar_debug_excel
from motor_ingestao import MotorIngestao


def main() -> None:
    parser = argparse.ArgumentParser(description="Motor de Ingestão Superfine — Fase 1")
    parser.add_argument(
        "--pasta",
        default=r"c:\Users\Usuario\Desktop\logistica",
        help="Pasta com PDF, XLSB e MSG do dia",
    )
    parser.add_argument("--pdf", default="", help="Caminho do PDF (opcional)")
    parser.add_argument("--xlsb", default="", help="Caminho do XLSB (opcional)")
    parser.add_argument("--msg", default="", help="Caminho do MSG (opcional)")
    args = parser.parse_args()

    pasta = Path(args.pasta)
    motor = MotorIngestao(str(pasta))
    consolidados = motor.executar(
        caminho_pdf=args.pdf,
        caminho_xlsb=args.xlsb,
        caminho_msg=args.msg,
    )

    data_hoje = date.today().isoformat()
    json_path = pasta / f"ingestao_{data_hoje}.json"
    xlsx_path = pasta / "DEBUG_INGESTAO.xlsx"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(motor.para_dict(), f, ensure_ascii=False, indent=2)

    gerar_debug_excel(motor, str(xlsx_path))

    resumo = motor.resumo()
    print("=" * 60)
    print("MOTOR DE INGESTÃO — SUPERFINE (FASE 1)")
    print("=" * 60)
    for chave, valor in resumo.items():
        print(f"  {chave}: {valor}")
    print("-" * 60)
    print(f"  JSON:  {json_path}")
    print(f"  Excel: {xlsx_path}")
    print("=" * 60)

    for item in consolidados:
        print(
            f"  {item.numero_pedido} | {item.cliente[:30]} | "
            f"{item.status} | {item.motivo_alocacao[:50]}"
        )


if __name__ == "__main__":
    main()
