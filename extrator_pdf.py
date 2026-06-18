"""
Extrator de PDF — Solicitação de Faturamento Superfine.
Estratégia: máquina de estados com pdfplumber (layout=True), sem LLM.

Uso:
    python extrator_pdf.py "teste leitura de pdf.pdf"
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pdfplumber

import config
from models import PedidoFaturamento
from normalizador import (
    normalizar_codigo_cliente,
    normalizar_pedido,
    normalizar_texto,
    parse_moeda_br,
    parse_peso_kg,
)

REGEX_INICIO_ITEM = re.compile(r"^(\d{3})\s+(\d{6}/\d{2}/\d{3})\s+(.+)$")
REGEX_PESO = re.compile(r"([\d.]+,\d{2})\s*(?:KG|ROLO)\b", re.IGNORECASE)
REGEX_DATA_PRODUCAO = re.compile(r"\b(\d{2}/\d{2}/\d{2})\b")
REGEX_MOEDA = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})")
REGEX_DESTINO = re.compile(r"^Destino:\s*(.+?)\s*-\s*(.+?)\s*$", re.IGNORECASE)
REGEX_TRANSP = re.compile(r"^Transp:\s*(\d+)\s*-\s*(.+?)\s*$", re.IGNORECASE)
REGEX_DESCRICAO = re.compile(r"^Descri[cç][aã]o:\s*(.+)$", re.IGNORECASE)
REGEX_OF_ANO = re.compile(r"\b(\d{6}/\d{2})\b")
REGEX_CLIENTE_COD = re.compile(r"(\d{5})\s*-\s*([A-ZÁÀÂÃÉÊÍÓÔÕÚÇa-z].*)")
REGEX_REPRESENTANTE = re.compile(
    r"Representante:\s*(\d+)\s*-\s*(.+?)(?=\s*Destino:|Transp:|Descri|$)",
    re.IGNORECASE,
)
REGEX_DIMENSAO_LONGA = re.compile(
    r"(?:^|[\s\-])(?:4[,.]800|5[,.]900)(?:\s*mm)?",
    re.IGNORECASE,
)

LINHAS_IGNORAR = (
    "SOLICITAÇÃO DE FATURAMENTO",
    "SOLICITACAO DE FATURAMENTO",
    "DATA PARA FATURAMENTO",
    "SOLICITANTE:",
    "TRANSPORTADORA:",
    "FILIAL:",
    "TOTAL PAG.",
    "NÚM PAG.",
    "NUM PAG.",
    "DATA DA IMPRESSÃO",
    "OBSERVAÇÃO OU COMENTÁRIO",
    "QTDE. ITENS:",
    "-- ",
)

ANCORAS_FIM_OBS = (
    "Descrição",
    "Descricao",
    "Condição",
    "Condicao",
    "Representante:",
    "Destino:",
    "Transp:",
    "Parcelas:",
)


REGEX_RETIRA_FOB = re.compile(
    r"(?:"
    r"(?:COLETA|COLETAR|RETIRA|RETIRAR|BUSCA|BUSCAR)\w*\s+(?:\w+\s+){0,6}"
    r"(?:FABRICA|FÁBRICA|SF|SUPERFINE|AQUI)"
    r"|"
    r"(?:FABRICA|FÁBRICA|SF|SUPERFINE|AQUI)\s+(?:\w+\s+){0,6}"
    r"(?:COLETA|COLETAR|RETIRA|RETIRAR|BUSCA|BUSCAR)\w*"
    r"|CLIENTE\s+RETIRA"
    r"|COLETA\s+NA\s+(?:SF|FABRICA|FÁBRICA)"
    r"|RETIRA\s+NA\s+(?:FABRICA|FÁBRICA)"
    r")",
    re.IGNORECASE,
)

REGEX_HUB_REDESPACHO = re.compile(
    r"LEVAR\s+NA\s+TRANSPORTADORA|REDESPACHO",
    re.IGNORECASE,
)


def _transportadora_superfine(texto_transp: str, codigo_transp: str) -> bool:
    codigo = normalizar_codigo_cliente(codigo_transp)
    if codigo == config.COD_SUPERFINE_TRANSP:
        return True
    transp = normalizar_texto(texto_transp)
    return bool(transp) and transp.startswith("SUPERFINE")


def classificar_frete(
    texto_observacao: str,
    texto_transp: str,
    texto_descricao: str = "",
    codigo_transp: str = "",
) -> str:
    """
    Classifica intenção logística via regex em observação e descrição.

    Prioridade: RETIRA_FOB > ENTREGA_TERCEIRO_HUB > SUPERFINE > TERCEIRO.
    """
    try:
        obs = normalizar_texto(texto_observacao)
        desc = normalizar_texto(texto_descricao)
        texto_intencao = f"{obs} {desc}"

        if REGEX_RETIRA_FOB.search(texto_intencao):
            return "RETIRA_FOB"

        if REGEX_HUB_REDESPACHO.search(texto_intencao):
            if not _transportadora_superfine(texto_transp, codigo_transp):
                return "ENTREGA_TERCEIRO_HUB"
            return "ENTREGA_DIRETA"

        if _transportadora_superfine(texto_transp, codigo_transp):
            return "ENTREGA_DIRETA"

        return "ENTREGA_TERCEIRO"
    except Exception:
        return "ENTREGA_TERCEIRO"


class ExtratorPDF:
    """Extrai pedidos de faturamento a partir de PDF Superfine."""

    def __init__(self, caminho_pdf: str) -> None:
        self.caminho_pdf = Path(caminho_pdf)
        self.avisos: list[str] = []
        self.erros: list[str] = []

    def extrair(self) -> list[PedidoFaturamento]:
        """Ponto de entrada: retorna lista de PedidoFaturamento."""
        pedidos: list[PedidoFaturamento] = []

        try:
            if not self.caminho_pdf.exists():
                self.erros.append(f"Arquivo não encontrado: {self.caminho_pdf}")
                return pedidos

            linhas = self._extrair_linhas_pdf()
            blocos = self._segmentar_blocos(linhas)

            for indice, bloco in enumerate(blocos, start=1):
                try:
                    pedido = self._parsear_bloco(bloco)
                    if pedido.numero_pedido:
                        pedidos.append(pedido)
                except Exception as exc:
                    self.erros.append(f"Bloco {indice}: {exc}")

            if not pedidos:
                self.avisos.append("Nenhum pedido extraído — verifique o layout do PDF.")

        except Exception as exc:
            self.erros.append(f"Falha geral na extração: {exc}")

        return pedidos

    def _extrair_linhas_pdf(self) -> list[str]:
        """Extrai texto; prefere modo sem layout quando preserva melhor as colunas."""
        linhas_sem_layout: list[str] = []
        linhas_com_layout: list[str] = []

        try:
            with pdfplumber.open(self.caminho_pdf) as pdf:
                for num_pag, pagina in enumerate(pdf.pages, start=1):
                    try:
                        texto_simples = pagina.extract_text() or ""
                        texto_layout = pagina.extract_text(layout=True) or ""

                        for texto in (texto_simples, texto_layout):
                            destino = (
                                linhas_sem_layout
                                if texto is texto_simples
                                else linhas_com_layout
                            )
                            if not texto.strip():
                                continue
                            for linha in texto.split("\n"):
                                linha_limpa = linha.strip()
                                if linha_limpa and not self._linha_ignoravel(linha_limpa):
                                    destino.append(linha_limpa)
                    except Exception as exc:
                        self.erros.append(f"Página {num_pag}: {exc}")
        except Exception as exc:
            self.erros.append(f"Erro ao abrir PDF: {exc}")

        blocos_simples = len(self._segmentar_blocos(linhas_sem_layout))
        blocos_layout = len(self._segmentar_blocos(linhas_com_layout))

        if blocos_simples >= blocos_layout:
            self.avisos.append(
                f"Modo extração: simples ({blocos_simples} blocos vs {blocos_layout} layout)."
            )
            return linhas_sem_layout

        self.avisos.append(
            f"Modo extração: layout ({blocos_layout} blocos vs {blocos_simples} simples)."
        )
        return linhas_com_layout

    @staticmethod
    def _linha_ignoravel(linha: str) -> bool:
        upper = normalizar_texto(linha)
        return any(upper.startswith(ign) or ign in upper for ign in LINHAS_IGNORAR)

    def _segmentar_blocos(self, linhas: list[str]) -> list[list[str]]:
        """Cada bloco começa com ^\\d{3}\\s+\\d{6}/\\d{2}/\\d{3}."""
        blocos: list[list[str]] = []
        bloco_atual: list[str] = []

        for linha in linhas:
            if REGEX_INICIO_ITEM.match(linha):
                if bloco_atual:
                    blocos.append(bloco_atual)
                bloco_atual = [linha]
            elif bloco_atual:
                bloco_atual.append(linha)

        if bloco_atual:
            blocos.append(bloco_atual)

        return blocos

    def _parsear_bloco(self, bloco: list[str]) -> PedidoFaturamento:
        """Parseia um bloco de linhas em um PedidoFaturamento."""
        pedido = PedidoFaturamento()
        pedido.bloco_bruto = "\n".join(bloco)

        try:
            primeira = bloco[0]
            match_inicio = REGEX_INICIO_ITEM.match(primeira)
            if not match_inicio:
                pedido.erro_extracao = "Cabeçalho de item inválido."
                return pedido

            pedido.sequencia = match_inicio.group(1)
            pedido.numero_pedido = match_inicio.group(2)
            pedido.numero_pedido_norm = normalizar_pedido(pedido.numero_pedido)
            resto_primeira = match_inicio.group(3)

            texto_bloco = " ".join(bloco)

            match_peso = REGEX_PESO.search(texto_bloco)
            if match_peso:
                pedido.peso_raw = match_peso.group(1)
                pedido.peso_kg = parse_peso_kg(pedido.peso_raw)

            pedido.valor_tt_raw, pedido.data_producao = self._extrair_tt_e_data(
                resto_primeira, texto_bloco
            )
            pedido.valor_tt = parse_moeda_br(pedido.valor_tt_raw)

            pedido.cliente_codigo, pedido.cliente_nome, pedido.of_ano = (
                self._extrair_cliente_e_of(resto_primeira, bloco)
            )

            capturando_descricao = False
            destino_match = re.search(
                r"Destino:\s*(.+?)\s*-\s*(.+?)(?=\s*Transp:|Representante:|$)",
                texto_bloco,
                re.IGNORECASE,
            )
            if destino_match:
                pedido.cidade = destino_match.group(1).strip()
                pedido.estado = destino_match.group(2).strip()
                pedido.cidade_destino = normalizar_texto(pedido.cidade)
                pedido.estado_destino = normalizar_texto(pedido.estado)

            transp_match = re.search(
                r"Transp:\s*(\d+)\s*-\s*(.+?)(?=\s*Destino:|Representante:|$)",
                texto_bloco,
                re.IGNORECASE,
            )
            if transp_match:
                pedido.transportadora_codigo = transp_match.group(1).strip()
                pedido.transportadora = transp_match.group(2).strip()

            for linha in bloco[1:]:
                try:
                    if match := REGEX_DESTINO.match(linha):
                        pedido.cidade = match.group(1).strip()
                        pedido.estado = match.group(2).strip()
                        pedido.cidade_destino = normalizar_texto(pedido.cidade)
                        pedido.estado_destino = normalizar_texto(pedido.estado)
                        capturando_descricao = False
                    elif match := REGEX_TRANSP.match(linha):
                        pedido.transportadora_codigo = match.group(1).strip()
                        pedido.transportadora = match.group(2).strip()
                        capturando_descricao = False
                    elif match := REGEX_DESCRICAO.match(linha):
                        pedido.descricao_item = match.group(1).strip()
                        capturando_descricao = True
                    elif capturando_descricao and not any(
                        linha.startswith(p) for p in ANCORAS_FIM_OBS
                    ):
                        pedido.descricao_item = (
                            f"{pedido.descricao_item} {linha.strip()}".strip()
                        )
                except Exception:
                    continue

            rep_match = REGEX_REPRESENTANTE.search(texto_bloco)
            if rep_match:
                pedido.representante = normalizar_texto(rep_match.group(2))

            pedido.observacao_comercial = self._extrair_observacao(bloco)
            pedido.descricao_item = self._enriquecer_descricao(bloco, pedido.descricao_item)

            desc_upper = normalizar_texto(pedido.descricao_item)
            obs_upper = normalizar_texto(pedido.observacao_comercial)

            if "SPYDER" in desc_upper or "SPYDER" in obs_upper:
                pedido.is_spyder = "SIM"

            if REGEX_DIMENSAO_LONGA.search(pedido.descricao_item):
                pedido.is_dimensao_longa = "SIM"

            if pedido.is_dimensao_longa == "SIM":
                pedido.exige_syder = "SIM"

            # tipo_frete: classificado no motor_ingestao (aprendizado antes do regex)

        except Exception as exc:
            pedido.erro_extracao = str(exc)

        return pedido

    def _extrair_tt_e_data(
        self, resto_primeira: str, texto_bloco: str
    ) -> tuple[str, str]:
        """Valor monetário (TT) fica imediatamente antes da data dd/mm/aa."""
        try:
            match_data = REGEX_DATA_PRODUCAO.search(resto_primeira)
            if not match_data:
                match_data = REGEX_DATA_PRODUCAO.search(texto_bloco)

            data = match_data.group(1) if match_data else ""

            if match_data:
                trecho_antes = resto_primeira[: match_data.start()]
                moedas = REGEX_MOEDA.findall(trecho_antes)
                if moedas:
                    return moedas[-1], data

            moedas_bloco = REGEX_MOEDA.findall(texto_bloco)
            if moedas_bloco:
                return moedas_bloco[-1], data

            return "", data
        except Exception:
            return "", ""

    def _extrair_cliente_e_of(
        self, resto_primeira: str, bloco: list[str]
    ) -> tuple[str, str, str]:
        """Cliente no padrão NNNNN - NOME (pode estar após OF/peso na mesma linha)."""
        try:
            texto_bloco = " ".join(bloco)
            of_ano = ""
            match_of = REGEX_OF_ANO.search(texto_bloco)
            if match_of:
                of_ano = match_of.group(1)

            codigo = ""
            nome = ""
            for match in REGEX_CLIENTE_COD.finditer(texto_bloco):
                candidato = match.group(2).strip()
                if re.search(r"[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]", candidato[:3], re.IGNORECASE):
                    codigo = match.group(1)
                    nome = candidato
                    break

            if not nome:
                return "", resto_primeira.strip(), of_ano

            nome = re.split(r"\s+\d{6}/\d{2}\b", nome)[0]
            nome = re.split(r"\s+\d[\d.,]*\s*KG", nome, flags=re.I)[0]
            nome = re.split(r"\s+\d{2}/\d{2}/\d{2}\b", nome)[0]
            nome = re.sub(r"\s+", " ", nome).strip()

            for linha in bloco[1:]:
                if any(linha.startswith(p) for p in ANCORAS_FIM_OBS):
                    break
                if REGEX_CLIENTE_COD.search(linha):
                    break
                if (
                    linha
                    and not REGEX_DATA_PRODUCAO.match(linha)
                    and not REGEX_PESO.search(linha)
                    and not REGEX_OF_ANO.search(linha)
                    and not linha.startswith("Descri")
                    and not linha.startswith("Condi")
                ):
                    nome = f"{nome} {linha.strip()}".strip()

            nome = re.split(
                r"\b(?:Condi[cç][aã]o|Descri[cç][aã]o|Representante:|Destino:|Transp:)",
                nome,
                maxsplit=1,
            )[0].strip()
            nome = re.sub(r"\s+", " ", nome)

            return codigo, nome, of_ano
        except Exception:
            return "", "", ""

    @staticmethod
    def _enriquecer_descricao(bloco: list[str], descricao_atual: str) -> str:
        """Garante que termos em linhas separadas (ex.: SPYDER) entrem na descrição."""
        try:
            partes: list[str] = []
            capturando = False
            for linha in bloco:
                if REGEX_DESCRICAO.match(linha):
                    capturando = True
                    partes.append(REGEX_DESCRICAO.match(linha).group(1).strip())
                    continue
                if capturando:
                    if any(linha.startswith(p) for p in ANCORAS_FIM_OBS):
                        break
                    partes.append(linha.strip())
            if partes:
                return " ".join(partes).strip()
            return descricao_atual
        except Exception:
            return descricao_atual

    @staticmethod
    def _extrair_observacao(bloco: list[str]) -> str:
        """Texto comercial entre data de produção e linhas de Descrição/Condição."""
        try:
            obs_partes: list[str] = []
            capturando = False

            for linha in bloco:
                if REGEX_DATA_PRODUCAO.search(linha) and not capturando:
                    capturando = True
                    pos = REGEX_DATA_PRODUCAO.search(linha)
                    if pos:
                        resto = linha[pos.end() :].strip()
                        if resto:
                            obs_partes.append(resto)
                    continue

                if not capturando:
                    continue

                if any(linha.startswith(p) for p in ANCORAS_FIM_OBS):
                    break

                obs_partes.append(linha.strip())

            return " ".join(obs_partes).strip()
        except Exception:
            return ""

    def resumo_extracao(self, pedidos: list[PedidoFaturamento]) -> dict[str, str]:
        """Resumo para log/CLI — strings CSV."""
        try:
            numeros = ", ".join(p.numero_pedido for p in pedidos)
            retiras = ", ".join(
                p.numero_pedido for p in pedidos if p.tipo_frete == "RETIRA_FOB"
            )
            spyder = ", ".join(
                p.numero_pedido for p in pedidos if p.is_spyder == "SIM"
            )
            longos = ", ".join(
                p.numero_pedido for p in pedidos if p.is_dimensao_longa == "SIM"
            )
            return {
                "arquivo": str(self.caminho_pdf),
                "total_itens": str(len(pedidos)),
                "pedidos": numeros,
                "retiras_fob": retiras or "NENHUM",
                "spyder": spyder or "NENHUM",
                "dimensao_longa": longos or "NENHUM",
                "avisos": " | ".join(self.avisos) or "NENHUM",
                "erros": " | ".join(self.erros) or "NENHUM",
            }
        except Exception as exc:
            return {"erros": str(exc)}


def main() -> None:
    caminho = (
        sys.argv[1]
        if len(sys.argv) > 1
        else r"c:\Users\Usuario\Desktop\logistica\teste leitura de pdf.pdf"
    )

    extrator = ExtratorPDF(caminho)
    pedidos = extrator.extrair()
    resumo = extrator.resumo_extracao(pedidos)

    print("=" * 60)
    print("EXTRATOR PDF — SUPERFINE")
    print("=" * 60)
    for chave, valor in resumo.items():
        print(f"  {chave}: {valor}")
    print("-" * 60)

    for pedido in pedidos:
        print(
            f"  [{pedido.sequencia}] {pedido.numero_pedido} | "
            f"{pedido.cliente_nome[:40]} | "
            f"{pedido.peso_kg:.2f} kg | TT R$ {pedido.valor_tt:,.2f} | "
            f"{pedido.cidade}-{pedido.estado} | "
            f"frete={pedido.tipo_frete} | spyder={pedido.is_spyder} | "
            f"longo={pedido.is_dimensao_longa}"
        )
        if pedido.erro_extracao:
            print(f"    ERRO: {pedido.erro_extracao}")

    print("=" * 60)
    print(f"Total extraído: {len(pedidos)} pedidos (esperado: 28)")


if __name__ == "__main__":
    main()
