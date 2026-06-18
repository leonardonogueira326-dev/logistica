"""
Extrator de e-mail MSG — canhotos, qualidade e coletas paradas.
Fase 1: apenas texto puro; imagens geram warning (sem OCR).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import extract_msg

import config
from models import EventoEmail
from normalizador import normalizar_texto, parse_peso_kg

REGEX_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")


class ExtratorEmail:
    """Processa arquivos .msg do Outlook."""

    def __init__(self, caminho_msg: str) -> None:
        self.caminho_msg = Path(caminho_msg)
        self.avisos: list[str] = []
        self.erros: list[str] = []
        self.assunto: str = ""

    def extrair(self) -> list[EventoEmail]:
        eventos: list[EventoEmail] = []

        try:
            if not self.caminho_msg.exists():
                self.erros.append(f"Arquivo não encontrado: {self.caminho_msg}")
                return eventos

            msg = extract_msg.Message(str(self.caminho_msg))
            try:
                self.assunto = str(msg.subject or "")
                self._verificar_anexos(msg)
                corpo = msg.body or ""
                eventos = self._parsear_corpo(corpo)
            finally:
                msg.close()

        except Exception as exc:
            self.erros.append(f"Falha geral na extração MSG: {exc}")

        return eventos

    def _verificar_anexos(self, msg) -> None:
        try:
            for anexo in msg.attachments:
                nome = (anexo.longFilename or anexo.shortFilename or "").strip()
                if not nome:
                    continue
                ext = Path(nome).suffix.lower()
                if ext == ".xlsb":
                    self.avisos.append(
                        f"Anexo XLSB detectado ({nome}) — use extrator_excel.py."
                    )
                elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".gif"):
                    self.avisos.append(
                        f"Imagem anexada ({nome}) — OCR desativado na Fase 1."
                    )
        except Exception as exc:
            self.erros.append(f"Erro ao ler anexos: {exc}")

    def _parsear_corpo(self, corpo: str) -> list[EventoEmail]:
        eventos: list[EventoEmail] = []
        linhas = [l.strip() for l in corpo.splitlines() if l.strip()]

        i = 0
        while i < len(linhas):
            if not REGEX_DATA.match(linhas[i]):
                i += 1
                continue

            try:
                data = linhas[i]
                campos: list[str] = []
                j = i + 1
                while j < len(linhas) and len(campos) < 7:
                    if REGEX_DATA.match(linhas[j]) or linhas[j].upper() in (
                        "TOTAL",
                        "ATT.",
                    ):
                        break
                    campos.append(linhas[j])
                    j += 1

                if len(campos) < 6:
                    i += 1
                    continue

                evento = EventoEmail(
                    data=data,
                    cliente=campos[0],
                    nf=campos[1],
                    volume=campos[2],
                    peso_kg=campos[3],
                    bairro=campos[4],
                    cidade=campos[5],
                    observacao=campos[6] if len(campos) > 6 else "",
                )

                if self._linha_template(evento):
                    i = j
                    continue

                evento.tipo_evento = self._classificar_evento(evento)
                eventos.append(evento)
                i = j
            except Exception as exc:
                self.erros.append(f"Linha {i}: {exc}")
                i += 1

        return eventos

    @staticmethod
    def _linha_template(evento: EventoEmail) -> bool:
        cliente = normalizar_texto(evento.cliente)
        bairro = normalizar_texto(evento.bairro)
        cidade = normalizar_texto(evento.cidade)
        if cliente == "SPYDER / CARRETEL" and bairro == "BAIRRO" and cidade == "CIDADE":
            return True
        return False

    def _classificar_evento(self, evento: EventoEmail) -> str:
        try:
            obs = normalizar_texto(evento.observacao)
            cliente = normalizar_texto(evento.cliente)
            nf = normalizar_texto(evento.nf)

            if "CANHOTO" in obs:
                return config.COD_TRAVADO_COMERCIAL
            if "QUALIDADE" in obs or "QUALITA" in cliente:
                return config.COD_TRAVADO_COMERCIAL
            if nf == "COLETA" or "COLETA" in obs:
                return "COLETA"
            if "CLIENTE RETIRA" in obs or "RETIRA" in obs:
                return config.COD_RETIRA_FOB
            if "AGUARDANDO ROTA" in obs or "ROTA" in obs:
                return "PENDENCIA_ROTA"
            if "TRANSPORTADORA COLETA" in obs:
                return config.COD_TERCEIRO
            return "OUTRO"
        except Exception:
            return "OUTRO"

    def resumo_extracao(self, eventos: list[EventoEmail]) -> dict[str, str]:
        canhotos = ", ".join(
            e.cliente for e in eventos if e.tipo_evento == config.COD_TRAVADO_COMERCIAL
        )
        coletas = ", ".join(e.cliente for e in eventos if e.tipo_evento == "COLETA")
        return {
            "arquivo": str(self.caminho_msg),
            "assunto": self.assunto,
            "total_eventos": str(len(eventos)),
            "canhotos": canhotos or "NENHUM",
            "coletas": coletas or "NENHUM",
            "avisos": " | ".join(self.avisos) or "NENHUM",
            "erros": " | ".join(self.erros) or "NENHUM",
        }


def buscar_xlsb_na_pasta(pasta: Path) -> str:
    """Localiza arquivo NFPARADA*.xlsb na pasta de dados."""
    try:
        for arquivo in pasta.iterdir():
            if arquivo.suffix.lower() == ".xlsb":
                return str(arquivo)
    except Exception:
        pass
    return ""


def main() -> None:
    pasta = Path(r"c:\Users\Usuario\Desktop\logistica")
    caminho = sys.argv[1] if len(sys.argv) > 1 else None

    if not caminho:
        for arquivo in pasta.iterdir():
            if arquivo.suffix.lower() == ".msg":
                caminho = str(arquivo)
                break

    if not caminho:
        print("Nenhum arquivo MSG encontrado.")
        return

    extrator = ExtratorEmail(caminho)
    eventos = extrator.extrair()
    resumo = extrator.resumo_extracao(eventos)

    print("=" * 60)
    print("EXTRATOR EMAIL — SUPERFINE")
    print("=" * 60)
    for chave, valor in resumo.items():
        print(f"  {chave}: {valor}")
    print("-" * 60)
    for e in eventos:
        print(
            f"  {e.data} | {e.cliente[:25]} | NF={e.nf} | "
            f"{e.peso_kg} kg | {e.tipo_evento} | {e.observacao[:50]}"
        )


if __name__ == "__main__":
    main()
