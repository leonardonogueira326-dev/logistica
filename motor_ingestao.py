"""
Motor de Ingestão — consolida PDF, XLSB e MSG em visão unificada.
Enriquece pedidos com cadastro mestre de clientes (Ref. 8).
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import config
from extrator_clientes import obter_lookup_clientes
from extrator_email import ExtratorEmail, buscar_xlsb_na_pasta
from extrator_excel import ExtratorExcel
from aprendizado_regras import consultar_aprendizado
from extrator_pdf import ExtratorPDF, classificar_frete
from models import (
    EventoEmail,
    PedidoConsolidado,
    PedidoFaturamento,
    RetencaoFiscal,
)
from normalizador import (
    extrair_cidade_transportadora,
    normalizar_cliente,
    normalizar_codigo_cliente,
    normalizar_pedido,
    normalizar_texto,
    resolver_rota_logistica,
)
from param_manager import carregar_parametros
from quarentena import avaliar_quarentena


class MotorIngestao:
    """Orquestra extração e consolidação das três fontes diárias."""

    def __init__(self, pasta_dados: str) -> None:
        self.pasta_dados = Path(pasta_dados)
        self.avisos: list[str] = []
        self.erros: list[str] = []
        self.pedidos_pdf: list[PedidoFaturamento] = []
        self.retencoes_xlsb: list[RetencaoFiscal] = []
        self.eventos_email: list[EventoEmail] = []
        self.consolidados: list[PedidoConsolidado] = []
        self.params = carregar_parametros()
        self._lookup_clientes = obter_lookup_clientes(str(self.pasta_dados))
        if not self._lookup_clientes:
            self.avisos.append(
                "Cadastro mestre não encontrado — enriquecimento desabilitado."
            )
        else:
            self.avisos.append(
                f"Cadastro mestre carregado: {len(self._lookup_clientes)} clientes"
            )

    def executar(
        self,
        caminho_pdf: str = "",
        caminho_xlsb: str = "",
        caminho_msg: str = "",
    ) -> list[PedidoConsolidado]:
        try:
            caminho_pdf = caminho_pdf or self._buscar_arquivo(".pdf")
            caminho_xlsb = caminho_xlsb or buscar_xlsb_na_pasta(self.pasta_dados)
            caminho_msg = caminho_msg or self._buscar_arquivo(".msg")

            if caminho_pdf:
                ext_pdf = ExtratorPDF(caminho_pdf)
                self.pedidos_pdf = ext_pdf.extrair()
                self.avisos.extend(ext_pdf.avisos)
                self.erros.extend(ext_pdf.erros)
            else:
                self.erros.append("PDF de faturamento não encontrado na pasta.")

            if caminho_xlsb:
                ext_xlsb = ExtratorExcel(caminho_xlsb)
                self.retencoes_xlsb = ext_xlsb.extrair()
                self.avisos.extend(ext_xlsb.avisos)
                self.erros.extend(ext_xlsb.erros)
            else:
                self.avisos.append("XLSB não encontrado — bloqueios fiscais ignorados.")

            if caminho_msg:
                ext_msg = ExtratorEmail(caminho_msg)
                self.eventos_email = ext_msg.extrair()
                self.avisos.extend(ext_msg.avisos)
                self.erros.extend(ext_msg.erros)
            else:
                self.avisos.append("MSG não encontrado — bloqueios comerciais ignorados.")

            for pedido in self.pedidos_pdf:
                self._aplicar_classificacao_frete(pedido)
                self.enriquecer_cadastro_mestre(pedido)
            self.consolidados = self._consolidar()

        except Exception as exc:
            self.erros.append(f"Falha no motor de ingestão: {exc}")

        return self.consolidados

    def enriquecer_cadastro_mestre(self, pedido: PedidoFaturamento) -> None:
        """
        Enriquece endereço via cadastro mestre (código numérico sem zeros à esquerda).

        Regras geográficas:
        - ENTREGA_TERCEIRO_HUB: cidade da transportadora (redespacho) prevalece.
        - Frota própria / candidatos a LIBERADO: cadastro mestre é soberano.
        - RETIRA_FOB e ENTREGA_TERCEIRO externo: mantém PDF; mestre só complementa representante.
        """
        try:
            if not pedido.cidade_destino and pedido.cidade:
                pedido.cidade_destino = normalizar_texto(pedido.cidade)
            if not pedido.estado_destino and pedido.estado:
                pedido.estado_destino = normalizar_texto(pedido.estado)
            if not pedido.bairro_destino and pedido.bairro:
                pedido.bairro_destino = normalizar_texto(pedido.bairro)

            chave = normalizar_codigo_cliente(pedido.cliente_codigo)
            mestre = self._lookup_clientes.get(chave) if chave else None

            if pedido.tipo_frete == "ENTREGA_TERCEIRO_HUB":
                cidade_hub = extrair_cidade_transportadora(pedido.transportadora)
                if cidade_hub:
                    pedido.cidade_destino = normalizar_texto(cidade_hub)
                    pedido.cidade = pedido.cidade_destino
                else:
                    self.avisos.append(
                        f"Pedido {pedido.numero_pedido}: HUB sem cidade na linha Transp."
                    )
                if mestre:
                    pedido.representante = mestre["representante"]
                pedido.enriquecido_mestre = "HUB" if cidade_hub else "NAO"
                pedido.rota_logistica = resolver_rota_logistica(
                    pedido.cidade_destino, self.params
                )
                return

            if mestre and pedido.tipo_frete not in ("RETIRA_FOB", "ENTREGA_TERCEIRO"):
                pedido.bairro = mestre["bairro"]
                pedido.bairro_destino = mestre["bairro"]
                pedido.cidade = mestre["cidade"]
                pedido.cidade_destino = mestre["cidade"]
                pedido.cep = mestre["cep"]
                pedido.cep_destino = mestre["cep"]
                pedido.representante = mestre["representante"]
                pedido.enriquecido_mestre = "SIM"
            elif mestre:
                pedido.representante = mestre["representante"]
                pedido.enriquecido_mestre = "NAO"
                if chave:
                    self.avisos.append(
                        f"Cliente {pedido.cliente_codigo} ({pedido.cliente_nome}) "
                        f"— mestre não aplicado (frete {pedido.tipo_frete})."
                    )
            else:
                pedido.enriquecido_mestre = "NAO"
                pedido.representante = pedido.representante or "NÃO IDENTIFICADO"
                if chave:
                    self.avisos.append(
                        f"Cliente {pedido.cliente_codigo} ({pedido.cliente_nome}) "
                        f"não encontrado no cadastro mestre."
                    )

            cidade_rota = pedido.cidade_destino or normalizar_texto(pedido.cidade)
            pedido.rota_logistica = resolver_rota_logistica(cidade_rota, self.params)
        except Exception as exc:
            self.avisos.append(f"Enriquecimento {pedido.numero_pedido}: {exc}")

    def _aplicar_classificacao_frete(self, pedido: PedidoFaturamento) -> None:
        """Aprendizado local tem prioridade sobre regex estática."""
        try:
            aprendido = consultar_aprendizado(
                pedido.cliente_codigo,
                pedido.observacao_comercial,
                pedido.descricao_item,
            )
            if aprendido:
                status_aprendido, tipo_frete, palavra = aprendido
                pedido.tipo_frete = tipo_frete
                pedido.aprendizado_aplicado = "SIM"
                self.avisos.append(
                    f"Aprendizado aplicado {pedido.numero_pedido}: "
                    f"cliente {pedido.cliente_codigo}+{palavra} -> {status_aprendido}"
                )
                return

            pedido.tipo_frete = classificar_frete(
                pedido.observacao_comercial,
                pedido.transportadora,
                pedido.descricao_item,
                pedido.transportadora_codigo,
            )
            pedido.aprendizado_aplicado = "NAO"
        except Exception as exc:
            self.avisos.append(f"Classificação frete {pedido.numero_pedido}: {exc}")
            pedido.tipo_frete = classificar_frete(
                pedido.observacao_comercial,
                pedido.transportadora,
                pedido.descricao_item,
                pedido.transportadora_codigo,
            )

    def _buscar_arquivo(self, extensao: str) -> str:
        try:
            for arquivo in self.pasta_dados.iterdir():
                if arquivo.suffix.lower() == extensao:
                    return str(arquivo)
        except Exception:
            pass
        return ""

    def _consolidar(self) -> list[PedidoConsolidado]:
        mapa_fiscal = self._indexar_retencoes()
        mapa_email_cliente = self._indexar_eventos_email()
        consolidados: list[PedidoConsolidado] = []

        for pedido in self.pedidos_pdf:
            try:
                item = PedidoConsolidado(
                    numero_pedido=pedido.numero_pedido,
                    numero_pedido_norm=pedido.numero_pedido_norm,
                    cliente=pedido.cliente_nome,
                    cliente_codigo=pedido.cliente_codigo,
                    peso_kg=pedido.peso_kg,
                    valor_tt=pedido.valor_tt,
                    cidade=pedido.cidade_destino or pedido.cidade,
                    estado=pedido.estado_destino or pedido.estado,
                    bairro=pedido.bairro_destino or pedido.bairro,
                    cidade_destino=pedido.cidade_destino or normalizar_texto(pedido.cidade),
                    estado_destino=pedido.estado_destino or normalizar_texto(pedido.estado),
                    bairro_destino=pedido.bairro_destino or normalizar_texto(pedido.bairro),
                    cep=pedido.cep or pedido.cep_destino,
                    cep_destino=pedido.cep_destino or pedido.cep,
                    representante=pedido.representante or "NÃO IDENTIFICADO",
                    rota_logistica=pedido.rota_logistica,
                    enriquecido_mestre=pedido.enriquecido_mestre,
                    tipo_frete=pedido.tipo_frete,
                    is_spyder=pedido.is_spyder,
                    is_dimensao_longa=pedido.is_dimensao_longa,
                    exige_syder=pedido.exige_syder,
                    fontes="PDF",
                    observacao_comercial=pedido.observacao_comercial or pedido.descricao_item,
                    data_producao=pedido.data_producao,
                )

                status, motivo, auditoria = self._classificar_pedido(
                    pedido, mapa_fiscal, mapa_email_cliente
                )
                item.status = status
                item.motivo_bloqueio = motivo
                item.auditoria = auditoria
                item.motivo_alocacao = calcular_acondicionamento_e_restricoes(
                    pedido, self.params
                )

                revisao, motivo_q, palavra_q = avaliar_quarentena(
                    item.peso_kg,
                    item.observacao_comercial,
                    pedido.descricao_item,
                    pedido.aprendizado_aplicado,
                )
                item.revisao_obrigatoria = revisao
                item.motivo_quarentena = motivo_q
                item.palavra_chave_quarentena = palavra_q
                if revisao == config.COD_REVISAO_OBRIGATORIA:
                    item.auditoria = (
                        f"{item.auditoria} | {config.COD_REVISAO_OBRIGATORIA}: {motivo_q}"
                    ).strip(" |")

                consolidados.append(item)
            except Exception as exc:
                self.erros.append(f"Consolidação {pedido.numero_pedido}: {exc}")

        return consolidados

    def _indexar_retencoes(self) -> dict[str, RetencaoFiscal]:
        mapa: dict[str, RetencaoFiscal] = {}
        for retencao in self.retencoes_xlsb:
            if not retencao.motivo_coluna:
                continue
            if retencao.pedidos_expandidos:
                for pedido in retencao.pedidos_expandidos.split(","):
                    chave = normalizar_pedido(pedido.strip())
                    if chave:
                        mapa[chave] = retencao
            chave_raw = normalizar_pedido(retencao.pedido_raw)
            if chave_raw:
                mapa[chave_raw] = retencao
        return mapa

    def _indexar_eventos_email(self) -> dict[str, EventoEmail]:
        mapa: dict[str, EventoEmail] = {}
        for evento in self.eventos_email:
            chave = normalizar_cliente(evento.cliente)
            if chave:
                mapa[chave] = evento
        return mapa

    def _classificar_pedido(
        self,
        pedido: PedidoFaturamento,
        mapa_fiscal: dict[str, RetencaoFiscal],
        mapa_email: dict[str, EventoEmail],
    ) -> tuple[str, str, str]:
        auditorias: list[str] = []

        if pedido.tipo_frete == "RETIRA_FOB":
            return (
                config.COD_RETIRA_FOB,
                "COLETA NA FABRICA / RETIRA",
                "classificar_frete=RETIRA_FOB",
            )

        if pedido.tipo_frete == "ENTREGA_TERCEIRO_HUB":
            cidade_hub = extrair_cidade_transportadora(pedido.transportadora)
            return (
                config.COD_TERCEIRO_HUB,
                pedido.transportadora,
                f"classificar_frete=ENTREGA_TERCEIRO_HUB | hub_cidade={cidade_hub or 'NAO_EXTRAIDA'}",
            )

        if pedido.tipo_frete == "ENTREGA_TERCEIRO":
            return (
                config.COD_TERCEIRO,
                pedido.transportadora,
                "transportadora terceira no PDF",
            )

        retencao = mapa_fiscal.get(pedido.numero_pedido_norm)
        if retencao:
            auditorias.append(
                f"XLSB coluna={retencao.motivo_coluna} pedido={retencao.pedido_raw}"
            )
            return (
                config.COD_BLOQUEIO_FISCAL,
                f"{config.COD_BLOQUEIO_FISCAL} ({retencao.motivo_coluna})",
                " | ".join(auditorias),
            )

        cliente_norm = normalizar_cliente(pedido.cliente_nome)
        evento = self._buscar_evento_email(cliente_norm, mapa_email)
        if evento:
            auditorias.append(f"EMAIL tipo={evento.tipo_evento} nf={evento.nf}")
            if evento.tipo_evento == config.COD_TRAVADO_COMERCIAL:
                return (
                    config.COD_TRAVADO_COMERCIAL,
                    evento.observacao,
                    " | ".join(auditorias),
                )

        return config.COD_LIBERADO, "", " | ".join(auditorias) if auditorias else "sem bloqueio"

    @staticmethod
    def _buscar_evento_email(
        cliente_norm: str, mapa_email: dict[str, EventoEmail]
    ) -> EventoEmail | None:
        if cliente_norm in mapa_email:
            return mapa_email[cliente_norm]

        for chave, evento in mapa_email.items():
            if chave in cliente_norm or cliente_norm in chave:
                return evento

        palavras_cliente = set(cliente_norm.split())
        for chave, evento in mapa_email.items():
            palavras_chave = set(chave.split())
            if palavras_cliente & palavras_chave:
                return evento

        return None

    def resumo(self) -> dict[str, str]:
        liberados = sum(1 for c in self.consolidados if c.status == config.COD_LIBERADO)
        bloqueados_fiscal = sum(
            1 for c in self.consolidados if c.status == config.COD_BLOQUEIO_FISCAL
        )
        bloqueados_comercial = sum(
            1 for c in self.consolidados if c.status == config.COD_TRAVADO_COMERCIAL
        )
        retiras = sum(1 for c in self.consolidados if c.status == config.COD_RETIRA_FOB)
        terceiros = sum(1 for c in self.consolidados if c.status == config.COD_TERCEIRO)
        terceiros_hub = sum(
            1 for c in self.consolidados if c.status == config.COD_TERCEIRO_HUB
        )
        revisoes = sum(
            1
            for c in self.consolidados
            if c.revisao_obrigatoria == config.COD_REVISAO_OBRIGATORIA
        )
        enriquecidos = sum(
            1 for p in self.pedidos_pdf if p.enriquecido_mestre == "SIM"
        )

        return {
            "pedidos_pdf": str(len(self.pedidos_pdf)),
            "retencoes_xlsb": str(len(self.retencoes_xlsb)),
            "eventos_email": str(len(self.eventos_email)),
            "consolidados": str(len(self.consolidados)),
            "enriquecidos_mestre": f"{enriquecidos}/{len(self.pedidos_pdf)}",
            "cadastro_clientes": str(len(self._lookup_clientes)),
            "liberados": str(liberados),
            "bloqueio_fiscal": str(bloqueados_fiscal),
            "travado_comercial": str(bloqueados_comercial),
            "retira_fob": str(retiras),
            "terceiros": str(terceiros),
            "terceiros_hub": str(terceiros_hub),
            "revisao_obrigatoria": str(revisoes),
            "avisos": " | ".join(self.avisos) or "NENHUM",
            "erros": " | ".join(self.erros) or "NENHUM",
        }

    def para_dict(self) -> dict:
        return {
            "resumo": self.resumo(),
            "pedidos_pdf": [asdict(p) for p in self.pedidos_pdf],
            "retencoes_xlsb": [asdict(r) for r in self.retencoes_xlsb],
            "eventos_email": [asdict(e) for e in self.eventos_email],
            "consolidados": [asdict(c) for c in self.consolidados],
        }


def calcular_acondicionamento_e_restricoes(
    pedido: PedidoFaturamento, params: dict | None = None
) -> str:
    """
    Define regras de acondicionamento e restrições de alocação.
    SPYDER: SYDER obrigatório somente se dimensão longa.
    """
    try:
        params = params or carregar_parametros()
        peso_max_bau = float(params.get("peso_max_spyder_no_bau_kg", config.PESO_MAX_SPYDER_NO_BAU))
        motivos: list[str] = []

        if pedido.is_spyder == "SIM":
            if pedido.peso_kg <= peso_max_bau and config.PERMITIR_SPYDER_NO_BAU:
                motivos.append(config.OBS_SPYDER_LEVE_BAU)
            elif pedido.is_dimensao_longa == "SIM":
                motivos.append("EXIGE CARROCERIA SYDER (DIMENSÃO LONGA)")

        if pedido.is_dimensao_longa == "SIM":
            motivos.append("BLOQUEIO VAN MASTER — DIMENSÃO LONGA (4,800 / 5,900)")

        if pedido.exige_syder == "SIM":
            motivos.append("EXIGE SYDER")

        if pedido.tipo_frete == "RETIRA_FOB":
            motivos.append("RETIRA FOB — FORA DA FROTA PRÓPRIA")

        if pedido.tipo_frete == "ENTREGA_TERCEIRO_HUB":
            motivos.append("REDESPACHO HUB — ENTREGA NA TRANSPORTADORA TERCEIRA")

        return " | ".join(motivos) if motivos else "ALOCAÇÃO PADRÃO"
    except Exception as exc:
        return f"ERRO REGRA: {exc}"
