"""
Extrator de XLSB — Material Não Faturado (retenções fiscais/comerciais).
Lê automaticamente a última aba (da direita para esquerda).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from pyxlsb import open_workbook

import config
from models import RetencaoFiscal
from normalizador import expandir_pedidos_compostos, normalizar_texto, parse_peso_kg


class ExtratorExcel:
    """Extrai retenções da última aba do arquivo XLSB."""

    def __init__(self, caminho_xlsb: str) -> None:
        self.caminho_xlsb = Path(caminho_xlsb)
        self.avisos: list[str] = []
        self.erros: list[str] = []
        self.aba_lida: str = ""

    def extrair(self) -> list[RetencaoFiscal]:
        retencoes: list[RetencaoFiscal] = []

        try:
            if not self.caminho_xlsb.exists():
                self.erros.append(f"Arquivo não encontrado: {self.caminho_xlsb}")
                return retencoes

            with open_workbook(self.caminho_xlsb) as wb:
                if not wb.sheets:
                    self.erros.append("Arquivo XLSB sem abas.")
                    return retencoes

                self.aba_lida = wb.sheets[-1]
                self.avisos.append(f"Aba lida: {self.aba_lida}")

                with wb.get_sheet(self.aba_lida) as sheet:
                    headers: dict[int, str] = {}
                    for idx, row in enumerate(sheet.rows()):
                        valores = [c.v for c in row]
                        try:
                            if idx == 0:
                                headers = self._mapear_headers(valores)
                                continue

                            retencao = self._parsear_linha(valores, headers)
                            if retencao and retencao.pedido_raw:
                                retencoes.append(retencao)
                        except Exception as exc:
                            self.erros.append(f"Linha {idx + 1}: {exc}")

        except Exception as exc:
            self.erros.append(f"Falha geral na extração XLSB: {exc}")

        return retencoes

    def _mapear_headers(self, valores: list) -> dict[int, str]:
        headers: dict[int, str] = {}
        for i, val in enumerate(valores):
            if val is None:
                continue
            nome = normalizar_texto(str(val))
            nome = (
                nome.replace("EXPORTAÇÃO", "EXPORTACAO")
                .replace("LOGÍSTICA", "LOGISTICA")
                .replace("OBS / FATURAR", "OBS_FATURAR")
            )
            headers[i] = nome
        return headers

    def _parsear_linha(
        self, valores: list, headers: dict[int, str]
    ) -> RetencaoFiscal | None:
        linha = {headers.get(i, f"COL_{i}"): v for i, v in enumerate(valores)}

        cliente = str(linha.get("CLIENTE") or "").strip()
        pedido_raw = str(linha.get("PEDIDO") or "").strip()
        if not cliente and not pedido_raw:
            return None

        retencao = RetencaoFiscal()
        retencao.cliente = cliente
        retencao.pedido_raw = pedido_raw
        retencao.pedidos_expandidos = expandir_pedidos_compostos(pedido_raw)
        retencao.data = self._converter_data(linha.get("DATA"))
        retencao.peso_kg = self._converter_peso(linha.get("PESO"))
        retencao.representante = str(linha.get("REPRESENTANTE") or "").strip()
        retencao.obs_faturar = str(linha.get("OBS_FATURAR") or "").strip()

        motivo_coluna, valor_bloqueio = self._detectar_bloqueio(linha)
        retencao.motivo_coluna = motivo_coluna
        retencao.valor_bloqueio = valor_bloqueio

        return retencao

    def _detectar_bloqueio(self, linha: dict) -> tuple[str, str]:
        for coluna in config.COLUNAS_BLOQUEIO_XLSB:
            valor = linha.get(coluna)
            if valor is not None and str(valor).strip() not in ("", "0", "0.0"):
                return coluna, str(valor)
        return "", ""

    @staticmethod
    def _converter_data(valor) -> str:
        try:
            if valor is None:
                return ""
            if isinstance(valor, (int, float)) and valor > 40000:
                data = datetime(1899, 12, 30) + timedelta(days=float(valor))
                return data.strftime("%d/%m/%Y")
            return str(valor).strip()
        except Exception:
            return str(valor or "")

    @staticmethod
    def _converter_peso(valor) -> float:
        try:
            if valor is None:
                return 0.0
            if isinstance(valor, (int, float)):
                return float(valor)
            return parse_peso_kg(str(valor))
        except Exception:
            return 0.0

    def resumo_extracao(self, retencoes: list[RetencaoFiscal]) -> dict[str, str]:
        bloqueados = ", ".join(
            r.pedido_raw for r in retencoes if r.motivo_coluna
        )
        return {
            "arquivo": str(self.caminho_xlsb),
            "aba": self.aba_lida,
            "total_linhas": str(len(retencoes)),
            "com_bloqueio": str(sum(1 for r in retencoes if r.motivo_coluna)),
            "pedidos_bloqueados": bloqueados[:500] or "NENHUM",
            "avisos": " | ".join(self.avisos) or "NENHUM",
            "erros": " | ".join(self.erros) or "NENHUM",
        }


def main() -> None:
    pasta = Path(r"c:\Users\Usuario\Desktop\logistica")
    caminho = sys.argv[1] if len(sys.argv) > 1 else None

    if not caminho:
        for arquivo in pasta.iterdir():
            if arquivo.suffix.lower() == ".xlsb" and "NFPARADA" in arquivo.name.upper():
                caminho = str(arquivo)
                break

    if not caminho:
        print("Nenhum arquivo XLSB encontrado.")
        return

    extrator = ExtratorExcel(caminho)
    retencoes = extrator.extrair()
    resumo = extrator.resumo_extracao(retencoes)

    print("=" * 60)
    print("EXTRATOR XLSB — SUPERFINE")
    print("=" * 60)
    for chave, valor in resumo.items():
        print(f"  {chave}: {valor}")
    print("-" * 60)
    for r in retencoes[:10]:
        print(
            f"  {r.pedido_raw} | {r.cliente[:30]} | "
            f"bloqueio={r.motivo_coluna} | expandidos={r.pedidos_expandidos[:60]}"
        )


if __name__ == "__main__":
    main()
