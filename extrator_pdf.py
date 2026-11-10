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
    montar_id_item,
    normalizar_codigo_cliente,
    normalizar_pedido,
    normalizar_texto,
    parse_moeda_br,
    parse_peso_kg,
)

MARCADOR_OBS = "\u00a7OBS\u00a7 "
MARCADOR_OF = "\u00a7OF\u00a7 "
REGEX_SOLICITACAO = re.compile(r"Solicita[cç][aã]o de Faturamento\s*N[°ºo]?\s*(\d+)", re.IGNORECASE)
REGEX_DATA_FATURAMENTO = re.compile(r"Data para Faturamento:\s*(\d{2}/\d{2}/\d{2,4})", re.IGNORECASE)
REGEX_INICIO_ITEM = re.compile(r"^(\d{3})\s+(\d{6}/\d{2}/\d{3})\s+(.+)$")
REGEX_PESO = re.compile(r"([\d.]+,\d{2})\s*(?:KG|ROLO)\b", re.IGNORECASE)
# Itens vendidos por peça (carretel, caixa): Qtde. vem em PÇ/PÇS/UN/CX
REGEX_QTDE_PECA = re.compile(r"([\d.]+,\d{2})\s*(?:P[ÇC]S?|UN|UND|CX|CXS|CAIXAS?)(?=\s|$)", re.IGNORECASE)
# Peso de cada peça na descrição: "0,600mm 900GR", "1KG", "12,5Kg", "10 GR C/50 UN"
REGEX_PESO_PECA = re.compile(
    r"(?<![\d.,])(\d{1,4}(?:[.,]\d{1,3})?)\s*(KG|GRS?|G)\b(?:\s*C/\s*(\d+)\s*UN)?",
    re.IGNORECASE,
)


def peso_por_peca_kg(texto: str) -> float:
    """Peso (kg) de uma peça a partir da descrição; 0 se não achar."""
    for m in REGEX_PESO_PECA.finditer(texto or ""):
        valor = float(m.group(1).replace(".", "").replace(",", ".")) if "," in m.group(1) else float(m.group(1))
        kg = valor if m.group(2).upper() == "KG" else valor / 1000
        if m.group(3):  # "10 GR C/50 UN" -> caixa com 50
            kg *= int(m.group(3))
        if kg > 0:
            return round(kg, 4)
    return 0.0
REGEX_DATA_PRODUCAO = re.compile(r"\b(\d{2}/\d{2}/\d{2})\b")
REGEX_MOEDA = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})")
REGEX_DESTINO = re.compile(r"^Destino:\s*(.+?)\s*-\s*(.+?)\s*$", re.IGNORECASE)
REGEX_TRANSP = re.compile(r"^Transp:\s*(\d+)\s*-\s*(.+?)\s*$", re.IGNORECASE)
REGEX_DESCRICAO = re.compile(r"^Descri[cç][aã]o:\s*(.+)$", re.IGNORECASE)
REGEX_OF_ANO = re.compile(r"(?<![\d/])(\d{6}/\d{2})(?![\d/])")
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
    r"(?:LEVAR?|ENTREGAR?|DEIXAR?)\s+(?:NA|NO|PARA\s+A|AT[EÉ](?:\s+A)?)\s+TRANSP\w*|REDESPACHO",
    re.IGNORECASE,
)

REGEX_PALAVRAS_CHAVE_LOGISTICA = re.compile(
    r"COLETA|RETIRA|BUSCAR|REDESPACHO|LEVAR\s+NA\s+TRANSP\w*|\bFOB\b|\bHUB\b",
    re.IGNORECASE,
)

REGEX_PALAVRAS_CHAVE_FRETE = re.compile(
    r"COLETA|RETIRA|BUSCAR|REDESPACHO|LEVAR\s+NA\s+TRANSP\w*|FOB|HUB|FABRICA|FÁBRICA",
    re.IGNORECASE,
)

REGEX_PALAVRAS_ADMINISTRATIVAS = re.compile(
    r"PAGAMENTO|PGTO|BOLETO|BOLETOS|T[IÍ]TULO|T[IÍ]TULOS|DECRETO|"
    r"HOR[AÁ]RIO|DESCONTO|VENCIMENTO|COBRAN[CÇ]A|FACTORING|F[EÉ]RIAS|DDL|EMAIL",
    re.IGNORECASE,
)


# Texto fiscal padrão que aparece em quase toda observação. Não carrega
# instrução logística, mas contém "DECRETO" e fazia o filtro achar que a
# observação inteira era administrativa (a IA nunca era chamada).
REGEX_TEXTO_PADRAO = re.compile(
    r"-?\s*Redu[cç][aã]o\s+do\s+DECRETO\s+N[º°o]?\s*11\.?055\s*,?\s*DE\s+28\s+DE\s+ABRIL\s+DE\s+2022\s*-?",
    re.IGNORECASE,
)


def remover_texto_padrao(texto: str) -> str:
    """Remove trechos-padrão (decreto fiscal) antes de analisar a observação."""
    return re.sub(r"\s+", " ", REGEX_TEXTO_PADRAO.sub(" ", texto or "")).strip(" -")


def _transportadora_superfine(texto_transp: str, codigo_transp: str) -> bool:
    codigo = normalizar_codigo_cliente(codigo_transp)
    if codigo == config.COD_SUPERFINE_TRANSP:
        return True
    transp = normalizar_texto(texto_transp)
    return bool(transp) and transp.startswith("SUPERFINE")


def tem_palavras_chave_logisticas(
    texto_observacao: str,
    texto_descricao: str = "",
) -> bool:
    """Indica se há palavras-chave logísticas explícitas no texto."""
    texto = f"{normalizar_texto(texto_observacao)} {normalizar_texto(texto_descricao)}"
    return bool(texto.strip() and REGEX_PALAVRAS_CHAVE_LOGISTICA.search(texto))


def observacao_apenas_administrativa(
    texto_observacao: str,
    texto_descricao: str = "",
) -> bool:
    """
    True quando a observação é puramente administrativa (pagamento, boleto, etc.)
    sem instrução logística forte — candidata a pular a IA.
    """
    obs = normalizar_texto(remover_texto_padrao(texto_observacao))
    desc = normalizar_texto(texto_descricao)
    texto = f"{obs} {desc}".strip()
    if not texto:
        return False
    if not REGEX_PALAVRAS_ADMINISTRATIVAS.search(texto):
        return False
    if tem_palavras_chave_logisticas(texto_observacao, texto_descricao):
        return False
    texto_intencao = f"{obs} {desc}"
    if REGEX_RETIRA_FOB.search(texto_intencao) or REGEX_HUB_REDESPACHO.search(texto_intencao):
        return False
    return True


def tipo_frete_padrao_superfine(
    texto_transp: str,
    codigo_transp: str,
    tipo_frete_atual: str,
) -> str:
    """LIBERADO / frota própria quando transportadora Superfine; senão mantém regex."""
    if _transportadora_superfine(texto_transp, codigo_transp):
        return "ENTREGA_DIRETA"
    return tipo_frete_atual


def classificar_frete_com_confianca(
    texto_observacao: str,
    texto_transp: str,
    texto_descricao: str = "",
    codigo_transp: str = "",
) -> tuple[str, bool]:
    """
    Classifica intenção logística via regex.

    Retorna (tipo_frete, confianca_alta). confianca_alta=False indica fallback
    ambíguo (ex.: ENTREGA_TERCEIRO genérico sem palavra-chave).
    """
    try:
        obs = normalizar_texto(texto_observacao)
        desc = normalizar_texto(texto_descricao)
        texto_intencao = f"{obs} {desc}"

        if REGEX_RETIRA_FOB.search(texto_intencao):
            return "RETIRA_FOB", True

        # A "transportadora" do PDF pode ser o próprio cliente buscando:
        # "Transp: 00347 - RETIRA NA FABRICA"
        if re.search(r"\bRETIRA\b|CLIENTE\s+BUSCA", normalizar_texto(texto_transp)):
            return "RETIRA_FOB", True

        if REGEX_HUB_REDESPACHO.search(texto_intencao):
            if not _transportadora_superfine(texto_transp, codigo_transp):
                return "ENTREGA_TERCEIRO_HUB", True
            return "ENTREGA_DIRETA", True

        if _transportadora_superfine(texto_transp, codigo_transp):
            return "ENTREGA_DIRETA", True

        if tem_palavras_chave_logisticas(texto_observacao, texto_descricao):
            return "ENTREGA_TERCEIRO", True

        return "ENTREGA_TERCEIRO", False
    except Exception:
        return "ENTREGA_TERCEIRO", False


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
    tipo, _ = classificar_frete_com_confianca(
        texto_observacao, texto_transp, texto_descricao, codigo_transp
    )
    return tipo


class ExtratorPDF:
    """Extrai pedidos de faturamento a partir de PDF Superfine."""

    def __init__(self, caminho_pdf: str) -> None:
        self.caminho_pdf = Path(caminho_pdf)
        self.avisos: list[str] = []
        self.erros: list[str] = []
        self._ultimo_modo_colunas = False

    def extrair(self) -> list[PedidoFaturamento]:
        """Ponto de entrada: retorna lista de PedidoFaturamento."""
        pedidos: list[PedidoFaturamento] = []

        try:
            if not self.caminho_pdf.exists():
                self.erros.append(f"Arquivo não encontrado: {self.caminho_pdf}")
                return pedidos

            linhas = self._extrair_linhas_pdf()
            blocos = self._segmentar_blocos(linhas)
            solicitacao, data_fat = self._ler_cabecalho()

            for indice, bloco in enumerate(blocos, start=1):
                try:
                    pedido = self._parsear_bloco(bloco)
                    pedido.numero_solicitacao = solicitacao
                    pedido.data_faturamento = data_fat
                    pedido.id_item = montar_id_item(
                        pedido.numero_pedido, pedido.of_ano, pedido.sequencia
                    )
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
        """Extrai linhas; prefere o modo por colunas (posição x das palavras)."""
        try:
            linhas_colunas = self._extrair_linhas_por_coluna()
        except Exception as exc:  # noqa: BLE001
            linhas_colunas = []
            self.avisos.append(f"Modo colunas falhou ({exc}); usando texto corrido.")
        if linhas_colunas:
            blocos = len(self._segmentar_blocos(linhas_colunas))
            if blocos:
                self.avisos.append(f"Modo extração: colunas ({blocos} blocos).")
                self._ultimo_modo_colunas = True
                return linhas_colunas
        return self._extrair_linhas_texto_corrido()

    def _extrair_linhas_por_coluna(self) -> list[str]:
        """
        Lê as palavras com coordenadas e separa a coluna "Observação" do resto.

        No relatório do ERP a coluna da direita (a partir do cabeçalho "Observação")
        contém, nesta ordem: o texto da observação, depois Representante:, Destino:
        e Transp:. No texto corrido essas colunas se misturam com o nome do cliente
        (ex.: "CEVI ... PAGAMENTO ANTECIPADO"). Aqui a observação sai em linhas
        marcadas com MARCADOR_OBS e o resto segue o formato que o parser já entende.
        """
        saida: list[str] = []
        with pdfplumber.open(self.caminho_pdf) as pdf:
            for num_pag, pagina in enumerate(pdf.pages, start=1):
                palavras = pagina.extract_words(keep_blank_chars=False)
                cab = [
                    w for w in palavras
                    if w["text"].startswith("Observa") and w["x0"] > pagina.width * 0.4
                ]
                if not cab:
                    if num_pag == 1:
                        return []
                    continue
                x_obs = cab[0]["x0"] - 4
                topo_cab = cab[0]["bottom"]
                cab_of = [w for w in palavras if w["text"].startswith("OF/") and w["top"] <= topo_cab + 1]
                x_of = cab_of[0]["x0"] if cab_of else None

                linhas_visuais: list[list[dict]] = []
                for w in sorted(palavras, key=lambda w: (w["top"], w["x0"])):
                    if w["top"] <= topo_cab:
                        continue
                    if linhas_visuais and abs(w["top"] - linhas_visuais[-1][0]["top"]) <= 2.5:
                        linhas_visuais[-1].append(w)
                    else:
                        linhas_visuais.append([w])

                campo_estruturado = False
                for linha in linhas_visuais:
                    esq = " ".join(w["text"] for w in sorted(linha, key=lambda w: w["x0"]) if w["x0"] < x_obs)
                    dir_ = " ".join(w["text"] for w in sorted(linha, key=lambda w: w["x0"]) if w["x0"] >= x_obs)
                    esq, dir_ = esq.strip(), dir_.strip()

                    if esq and self._linha_ignoravel(esq):
                        break  # rodapé da página
                    if esq and REGEX_INICIO_ITEM.match(esq):
                        campo_estruturado = False
                    if esq:
                        saida.append(esq)
                    if esq and REGEX_INICIO_ITEM.match(esq) and x_of is not None:
                        of_coluna = self._ler_of_por_caracteres(pagina, linha[0]["top"], x_of)
                        if of_coluna:
                            saida.append(f"{MARCADOR_OF}{of_coluna}")
                    if not dir_:
                        continue
                    if re.match(r"^(Representante:|Destino:|Transp:)", dir_, re.IGNORECASE):
                        campo_estruturado = True
                    if campo_estruturado:
                        saida.append(dir_)
                    else:
                        saida.append(f"{MARCADOR_OBS}{dir_}")
        return saida

    def _ler_cabecalho(self) -> tuple[str, str]:
        """Nº da solicitação e data para faturamento (cabeçalho da 1ª página)."""
        try:
            with pdfplumber.open(self.caminho_pdf) as pdf:
                texto = pdf.pages[0].extract_text() or ""
        except Exception:  # noqa: BLE001
            return "", ""
        m_sol = REGEX_SOLICITACAO.search(texto)
        m_data = REGEX_DATA_FATURAMENTO.search(texto)
        return (m_sol.group(1) if m_sol else "", m_data.group(1) if m_data else "")

    @staticmethod
    def _ler_of_por_caracteres(pagina, topo_linha: float, x_of: float) -> str:
        """
        Lê a OF caractere a caractere dentro da coluna "OF/Ano".

        Quando o nome do cliente é longo, o PDF sobrepõe as letras do nome aos
        dígitos da OF ("D0E0 4887/26" = "DE" + "004887/26"). Pela posição x dá
        para separar: só dígitos e "/" dentro da faixa da coluna.
        """
        faixa = (x_of - 2, x_of + 45)
        chars = [
            c for c in pagina.chars
            if abs(c["top"] - topo_linha) < 3 and faixa[0] <= c["x0"] < faixa[1]
            and (c["text"].isdigit() or c["text"] == "/")
        ]
        texto = "".join(c["text"] for c in sorted(chars, key=lambda c: c["x0"]))
        m = re.fullmatch(r"(\d{6}/\d{2})", texto)
        return m.group(1) if m else ""

    def _extrair_linhas_texto_corrido(self) -> list[str]:
        """Modo antigo: texto corrido; prefere sem layout quando preserva melhor as colunas."""
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
        pedido.bloco_bruto = "\n".join(l.replace(MARCADOR_OBS, "[OBS] ").replace(MARCADOR_OF, "[OF] ") for l in bloco)
        obs_coluna = [l[len(MARCADOR_OBS):].strip() for l in bloco if l.startswith(MARCADOR_OBS)]
        of_coluna = next((l[len(MARCADOR_OF):].strip() for l in bloco if l.startswith(MARCADOR_OF)), "")
        bloco = [l for l in bloco if not l.startswith((MARCADOR_OBS, MARCADOR_OF))]

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
            if of_coluna:
                pedido.of_ano = of_coluna
            # Restos da OF sobreposta no fim do nome ("RKR ... D0E0 4887/26")
            pedido.cliente_nome = re.sub(r"\s*\S*\d\S*\s+\d{3,6}/\d{2}\b", "", pedido.cliente_nome).strip()

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

            if not pedido.cidade_destino:
                # Texto sobreposto no PDF pode "engolir" o rótulo Destino:
                # (ex.: "27D87e,s7t5ino:"). A linha CIDADE - UF antes de Transp: resolve.
                for idx, linha in enumerate(bloco):
                    if linha.startswith("Transp:") and idx > 0:
                        m = re.match(r"^([A-ZÀ-Ú][A-ZÀ-Ú' .]+?)\s+-\s+([A-ZÀ-Ú ]+)$", bloco[idx - 1].strip())
                        if m:
                            pedido.cidade = m.group(1).strip()
                            pedido.estado = m.group(2).strip()
                            pedido.cidade_destino = normalizar_texto(pedido.cidade)
                            pedido.estado_destino = normalizar_texto(pedido.estado)
                        break

            # Transp: quebrou a linha ("..., 1233," / "GUARULHOS - 07221-080 - ...")
            for idx, linha in enumerate(bloco[:-1]):
                if linha.startswith("Transp:") and pedido.transportadora:
                    seguinte = bloco[idx + 1].strip()
                    if re.match(r"^[A-ZÀ-Ú][A-ZÀ-Ú' .]+\s-\s\d{5}-?\d{3}", seguinte):
                        pedido.transportadora = f"{pedido.transportadora} {seguinte}"
                    break

            # Representante: na própria linha (a linha seguinte pode ser da descrição, ex. "CAIXA")
            rep_match = next(
                (m for l in bloco if (m := REGEX_REPRESENTANTE.search(l))), None
            ) or REGEX_REPRESENTANTE.search(texto_bloco)
            if rep_match:
                pedido.representante = normalizar_texto(rep_match.group(2))

            if obs_coluna:
                pedido.observacao_comercial = re.sub(r"\s+", " ", " ".join(obs_coluna)).strip()
            elif not self._ultimo_modo_colunas:
                pedido.observacao_comercial = self._extrair_observacao(bloco)
            pedido.descricao_item = self._enriquecer_descricao(bloco, pedido.descricao_item)

            if not pedido.peso_kg and (m_peca := REGEX_QTDE_PECA.search(resto_primeira)):
                # Peça (carretel/caixa): peso = quantidade x peso da peça na descrição.
                # A 2ª linha da descrição pode cair fora do "Descrição:" (colunas) -> olha o bloco todo.
                qtde = parse_peso_kg(m_peca.group(1))
                texto_desc = " ".join(
                    [pedido.descricao_item]
                    + [l for l in bloco[1:] if not l.startswith(("Transp:", "Representante:", "Destino:"))]
                )
                unitario = peso_por_peca_kg(texto_desc)
                if qtde and unitario:
                    pedido.peso_kg = round(qtde * unitario, 2)
                    pedido.peso_raw = f"{m_peca.group(1)} pç x {unitario:g} kg"

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

            nome = re.split(r"\s*\d{6}/\d{2}\b", nome)[0]
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
