"""
Motor de Logística — clusterização por rotas, alocação de frota e jornada.
"""

from __future__ import annotations

import re

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import config
from pendencias import motivo_parado, pendencias
from models import ItemRota, PedidoConsolidado, RotaVeiculo
from normalizador import formatar_kg, normalizar_texto, resolver_rota_logistica
from param_manager import carregar_parametros, rotulo_rota


def _cid(obj: Any) -> str:
    """Identidade da carga (pedido/item + OF [+ parte]); cai no nº do pedido em dados antigos."""
    if isinstance(obj, dict):
        return str(obj.get("id_carga") or obj.get("id_item") or obj.get("numero_pedido") or "")
    return str(
        getattr(obj, "id_carga", "") or getattr(obj, "id_item", "") or getattr(obj, "numero_pedido", "")
    )


def _float(valor: Any) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _id_parte(id_item: str, n: int) -> str:
    return f"{id_item}@P{n}"


def _mesma_carga(obj: Any, chave: str) -> bool:
    """
    Compara pela identidade da carga. Aceita o nº do pedido puro (chamadas
    antigas), mas só quando a chave não traz OF — senão moveria a linha errada.
    """
    if _cid(obj) == chave:
        return True
    if "#" in (chave or ""):
        return False
    numero = obj.get("numero_pedido") if isinstance(obj, dict) else getattr(obj, "numero_pedido", "")
    return bool(chave) and numero == chave


@dataclass
class EstadoVeiculo:
    veiculo_id: str = ""
    veiculo_nome: str = ""
    veiculo_tipo: str = "BAU"
    capacidade_kg: float = 0.0
    itens: list[dict[str, Any]] = field(default_factory=list)
    rota_vocacao: str = ""
    regiao_predominante: str = ""
    peso_alocado: float = 0.0


class MotorLogistica:
    """Aloca pedidos liberados na frota respeitando peso, SPYDER e jornada."""

    def __init__(self, params: dict | None = None) -> None:
        self.params = params or carregar_parametros()
        self.rotas: list[RotaVeiculo] = []
        self.itens_por_veiculo: dict[str, list[ItemRota]] = {}
        self.backlog: list[dict[str, str]] = []
        self.backlog_futuro: list[dict[str, str]] = []
        self.backlog_local: list[dict[str, str]] = []
        self.coletas: list[dict[str, str]] = []
        self.itens_retorno_por_veiculo: dict[str, list[ItemRota]] = {}
        self.viagens_retorno_habilitadas: list[str] = []
        # Caminhões que o operador fechou: a sugestão automática não mexe neles.
        self.veiculos_fechados: list[str] = []
        # Caminhão montado que não saiu (motorista faltou, quebrou): a carga
        # volta para a próxima rota quando o dia seguinte for aberto.
        self.veiculos_nao_sairam: list[str] = []
        # vid -> {motorista, ajudante, placa} (vai para o romaneio)
        self.equipe_por_veiculo: dict[str, dict[str, str]] = {}
        # vid -> assinatura (ids na ordem) da última "Otimizar sequência";
        # se a carga mudou depois, a ordem deixa de valer como otimizada.
        self.sequencia_otimizada: dict[str, str] = {}
        # vid -> {assinatura, saida, volta, paradas: {chave: {chegada, espera, atraso, janela, origem}}}
        self.agenda: dict[str, dict[str, Any]] = {}
        self._cache_mapa_corredor: dict[str, int] = {}

    @staticmethod
    def _prefixo_cep(cep: str) -> str:
        digitos = "".join(c for c in str(cep or "") if c.isdigit())
        return digitos[:2] if len(digitos) >= 2 else ""

    def _mapa_prefixo_corredor(self) -> dict[str, int]:
        if self._cache_mapa_corredor:
            return self._cache_mapa_corredor
        mapa: dict[str, int] = {}
        for cid, info in self.params.get("corredores_logisticos", {}).items():
            try:
                corredor_id = int(str(cid))
            except ValueError:
                continue
            for pref in info.get("prefixos_cep", []):
                mapa[str(pref).zfill(2)[-2:]] = corredor_id
        self._cache_mapa_corredor = mapa
        return mapa

    def _corredor_pedido(self, pedido: dict[str, Any]) -> int | None:
        prefixo = self._prefixo_cep(str(pedido.get("cep_destino") or ""))
        if not prefixo:
            return None
        return self._mapa_prefixo_corredor().get(prefixo)

    def _corredor_dominante(self, itens: list[dict[str, Any]]) -> int | None:
        contagem: dict[int, int] = defaultdict(int)
        for item in itens:
            corredor = self._corredor_pedido(item)
            if corredor is not None:
                contagem[corredor] += 1
        if not contagem:
            return None
        return max(contagem, key=contagem.get)

    def _nome_corredor(self, corredor_id: int) -> str:
        info = self.params.get("corredores_logisticos", {}).get(str(corredor_id)) or {}
        return str(info.get("nome") or f"Corredor {corredor_id}")

    @staticmethod
    def _apelido_cliente(nome: str) -> str:
        m = re.search(r"\(([^()]+)\)\s*$", nome or "")
        return (m.group(1) if m else (nome or "")[:18]).strip()

    def verificar_efeito_elastico(self, veiculo_pedidos: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Detecta mistura de corredores rodoviários no caminhão e diz QUAIS:
        "Corredores misturados: Norte/Marginal (ZAGONEL, ATX) × Sul/ABC (BRIZANTE)".
        """
        por_corredor: dict[int, list[str]] = defaultdict(list)
        for pedido in veiculo_pedidos:
            corredor = self._corredor_pedido(pedido)
            if corredor is None:
                continue
            apelido = self._apelido_cliente(str(pedido.get("cliente") or ""))
            if apelido and apelido not in por_corredor[corredor]:
                por_corredor[corredor].append(apelido)

        if len(por_corredor) <= 1:
            return {"alerta_elastico": False, "mensagem_alerta_elastico": ""}

        # o corredor com menos clientes aparece por último (normalmente é o "intruso")
        ordem = sorted(por_corredor, key=lambda c: (-len(por_corredor[c]), c))
        partes = [f"{self._nome_corredor(c)} ({', '.join(por_corredor[c])})" for c in ordem]
        return {
            "alerta_elastico": True,
            "mensagem_alerta_elastico": "Corredores misturados: " + " × ".join(partes),
        }

    def _aplicar_alertas_rota(self, rota: RotaVeiculo, itens: list[dict[str, Any]]) -> None:
        self._aplicar_teo_rota(rota, itens)
        elastico = self.verificar_efeito_elastico(itens)
        rota.alerta_elastico = bool(elastico["alerta_elastico"])
        rota.mensagem_alerta_elastico = str(elastico.get("mensagem_alerta_elastico") or "")

    @staticmethod
    def _format_hhmm(minutos: int) -> str:
        h = max(0, minutos) // 60
        m = max(0, minutos) % 60
        return f"{h}h{m:02d}"

    @staticmethod
    def _id_retorno(veiculo_id: str) -> str:
        return f"{veiculo_id}{config.SUFIXO_VIAGEM_RETORNO}"

    @staticmethod
    def _parse_retorno_destino(destino: str) -> str | None:
        if destino.endswith(config.SUFIXO_VIAGEM_RETORNO):
            return destino[: -len(config.SUFIXO_VIAGEM_RETORNO)]
        return None

    @staticmethod
    def _eh_cidade_local(cidade: str) -> bool:
        norm = normalizar_texto(cidade).replace("'", " ")
        if norm in config.CIDADES_ENTREGA_LOCAL:
            return True
        if "SANTA BARBAR" in norm and "OESTE" in norm:
            return True
        return False

    def _tempo_viagem_cidade(self, cidade: str) -> int:
        norm = normalizar_texto(cidade).replace("'", " ")
        tempos_cidade = self.params.get("tempos_viagem_cidade_min", {})
        if norm in tempos_cidade:
            return int(tempos_cidade[norm])
        if norm == "SBO" and "SANTA BARBARA D OESTE" in tempos_cidade:
            return int(tempos_cidade["SANTA BARBARA D OESTE"])

        mapeamento = self.params.get("mapeamento_cidades_rotas", {})
        tempos_rota = self.params.get("tempos_viagem_rota_min", {})
        rota = mapeamento.get(norm, "ROTA_OUTROS")
        return int(tempos_rota.get(rota, tempos_rota.get("ROTA_OUTROS", 300)))

    def calcular_teo(self, itens: list[dict[str, Any]]) -> int:
        """TEO = o mesmo tempo de rota que o motor usa para decidir (calcular_tempo_rota)."""
        return self.calcular_tempo_rota(itens)

    def _aplicar_teo_rota(self, rota: RotaVeiculo, itens: list[dict[str, Any]]) -> None:
        teo = self.calcular_teo(itens)
        rota.teo_minutos = str(teo)
        rota.teo_hhmm = self._format_hhmm(teo)
        rota.segunda_viagem_elegivel = teo < config.TEO_SEGUNDA_VIAGEM_MAX_MIN

    def carregar_pedidos(self, consolidados: list[PedidoConsolidado]) -> list[dict[str, Any]]:
        from datetime import date as date_cls

        hoje = date_cls.today().isoformat()
        pedidos: list[dict[str, Any]] = []
        for c in consolidados:
            if c.status not in (config.COD_LIBERADO, config.COD_TERCEIRO_HUB):
                continue

            data_prev = (c.data_prevista_recebimento or "").strip()
            # "Hoje" = Data para Faturamento do PDF (reprocessar PDF antigo dá o mesmo resultado)
            referencia = (getattr(c, "data_referencia", "") or hoje).strip()
            limite = int(self.params.get("antecedencia_consulta_dias_uteis", 3))
            motivo_pendencia = motivo_parado(c, limite)
            if motivo_pendencia or (data_prev and data_prev > referencia):
                self.backlog_futuro.append(
                    {
                        "numero_pedido": c.numero_pedido,
                        "id_carga": c.id_item or c.numero_pedido,
                        "id_item": c.id_item or c.numero_pedido,
                        "of_ano": c.of_ano,
                        "obs_recebimento": getattr(c, "obs_recebimento", ""),
                        "entrega_em": getattr(c, "entrega_em", ""),
                        "entrega_cliente_codigo": getattr(c, "entrega_cliente_codigo", ""),
                        "pendente_desde": getattr(c, "pendente_desde", ""),
                        "data_producao": c.data_producao,
                        "cliente": c.cliente,
                        "cliente_codigo": c.cliente_codigo,
                        "representante": c.representante,
                        "bairro_destino": c.bairro_destino or c.bairro,
                        "cidade_destino": c.cidade_destino or c.cidade,
                        "rota_logistica": c.rota_logistica,
                        "peso_kg": str(c.peso_kg),
                        "motivo": motivo_pendencia or c.motivo_atraso or "RECEBIMENTO POSTERGADO",
                        "pendencias": ",".join(pendencias(c, limite)),
                        "consulta_representante": getattr(c, "consulta_representante", ""),
                        "dias_uteis_antecedencia": str(getattr(c, "dias_uteis_antecedencia", "") or ""),
                        "data_prevista_recebimento": data_prev,
                        "tipo_backlog": config.COD_BACKLOG_FUTURO,
                        "aceita_antecipacao": c.aceita_antecipacao or "SIM",
                        "is_spyder": c.is_spyder,
                        "is_dimensao_longa": c.is_dimensao_longa,
                        "exige_syder": c.exige_syder,
                        "enriquecido_mestre": c.enriquecido_mestre,
                    }
                )
                continue

            cidade = c.cidade_destino or c.cidade
            rota = c.rota_logistica or resolver_rota_logistica(cidade, self.params)

            if self._eh_cidade_local(cidade):
                self.backlog_local.append(
                    {
                        "numero_pedido": c.numero_pedido,
                        "id_carga": c.id_item or c.numero_pedido,
                        "id_item": c.id_item or c.numero_pedido,
                        "of_ano": c.of_ano,
                        "obs_recebimento": getattr(c, "obs_recebimento", ""),
                        "entrega_em": getattr(c, "entrega_em", ""),
                        "entrega_cliente_codigo": getattr(c, "entrega_cliente_codigo", ""),
                        "pendente_desde": getattr(c, "pendente_desde", ""),
                        "data_producao": c.data_producao,
                        "cliente": c.cliente,
                        "cliente_codigo": c.cliente_codigo,
                        "representante": c.representante,
                        "bairro_destino": c.bairro_destino or c.bairro,
                        "cidade_destino": cidade,
                        "rota_logistica": rota,
                        "peso_kg": str(c.peso_kg),
                        "motivo": "ENTREGA LOCAL",
                        "tipo_backlog": config.COD_BACKLOG_LOCAL,
                        "is_spyder": c.is_spyder,
                        "is_dimensao_longa": c.is_dimensao_longa,
                        "exige_syder": c.exige_syder,
                        "enriquecido_mestre": c.enriquecido_mestre,
                    }
                )
                continue

            pedidos.append(
                {
                    "numero_pedido": c.numero_pedido,
                    "id_carga": c.id_item or c.numero_pedido,
                    "id_item": c.id_item or c.numero_pedido,
                    "of_ano": c.of_ano,
                    "obs_recebimento": getattr(c, "obs_recebimento", ""),
                    "entrega_em": getattr(c, "entrega_em", ""),
                    "entrega_cliente_codigo": getattr(c, "entrega_cliente_codigo", ""),
                    "pendente_desde": getattr(c, "pendente_desde", ""),
                    "data_producao": c.data_producao,
                    "cliente": c.cliente,
                    "cliente_codigo": c.cliente_codigo,
                    "representante": c.representante,
                    "bairro_destino": c.bairro_destino or c.bairro,
                    "cidade_destino": cidade,
                    "estado_destino": c.estado_destino or c.estado,
                    "cep_destino": c.cep_destino,
                    "rota_logistica": rota,
                    "peso_kg": c.peso_kg,
                    "is_spyder": c.is_spyder,
                    "is_dimensao_longa": c.is_dimensao_longa,
                    "exige_syder": c.exige_syder,
                    "enriquecido_mestre": c.enriquecido_mestre,
                }
            )
        return pedidos

    def alocar_frota(
        self,
        consolidados: list[PedidoConsolidado],
        ativar_reserva: bool = False,
    ) -> tuple[list[RotaVeiculo], list[dict[str, str]]]:
        self.params = carregar_parametros()
        self._cache_mapa_corredor = {}
        self.backlog = []
        self.backlog_futuro = []
        self.backlog_local = []
        self.itens_retorno_por_veiculo = {}
        self.viagens_retorno_habilitadas = []
        pedidos = self.carregar_pedidos(consolidados)
        veiculos_ordem = self._ordem_veiculos(ativar_reserva)
        pedidos = self._dividir_excedentes(pedidos, veiculos_ordem)
        clusters = self._agrupar_por_rota(pedidos)

        estados: list[EstadoVeiculo] = []
        alocados_ids: set[str] = set()

        for vid, vinfo in veiculos_ordem:
            estado = EstadoVeiculo(
                veiculo_id=vid,
                veiculo_nome=vinfo.get("nome", vid),
                veiculo_tipo=vinfo.get("tipo", "BAU"),
                capacidade_kg=float(vinfo.get("capacidade_peso", 0)),
            )

            ancora = self._escolher_ancora(clusters, estado, alocados_ids)
            if not ancora:
                continue

            self._alocar_item(estado, ancora)
            alocados_ids.add(_cid(ancora))
            estado.rota_vocacao = ancora["rota_logistica"]
            estado.regiao_predominante = rotulo_rota(estado.rota_vocacao)

            fila = self._fila_priorizada(estado, clusters, alocados_ids)
            for pedido in fila:
                ok, _ = self.pode_alocar(pedido, estado)
                if ok:
                    self._alocar_item(estado, pedido)
                    alocados_ids.add(_cid(pedido))

            if estado.itens:
                estados.append(estado)

        self.backlog = []
        for rota, lista in clusters.items():
            for p in lista:
                if _cid(p) not in alocados_ids:
                    self.backlog.append(
                        {
                            "numero_pedido": p["numero_pedido"],
                            "id_carga": _cid(p),
                            "id_item": p.get("id_item", ""),
                            "of_ano": p.get("of_ano", ""),
                            "obs_recebimento": p.get("obs_recebimento", ""),
                            "entrega_em": p.get("entrega_em", ""),
                            "entrega_cliente_codigo": p.get("entrega_cliente_codigo", ""),
                            "pendente_desde": p.get("pendente_desde", ""),
                            "data_producao": p.get("data_producao", ""),
                            "parte": str(p.get("parte", "")),
                            "divisao_automatica": str(p.get("divisao_automatica", "") or ""),
                            "peso_total_linha": str(p.get("peso_total_linha", "") or ""),
                            "cliente": p["cliente"],
                            "representante": p["representante"],
                            "cidade_destino": p["cidade_destino"],
                            "rota_logistica": rota,
                            "peso_kg": str(p["peso_kg"]),
                            "motivo": config.COD_FROTA_INSUFICIENTE,
                        }
                    )

        self.rotas = [self._estado_para_rota(e) for e in estados]
        self.itens_por_veiculo = {
            e.veiculo_id: [self._dict_para_item(i, seq) for seq, i in enumerate(e.itens, 1)]
            for e in estados
        }
        self._calcular_oportunidades()
        return self.rotas, self.backlog

    # ------------------------------------------------------------------ quadro do dia
    MOTIVO_NOVA_LINHA = "NOVA LINHA — aguardando alocação"
    MOTIVOS_DO_SISTEMA = (config.COD_FROTA_INSUFICIENTE, MOTIVO_NOVA_LINHA)

    def _ids_item_no_quadro(self) -> set[str]:
        """
        Linhas que o operador já posicionou e a sugestão NÃO deve mexer: nos
        caminhões, entregas locais, coletas e na Fila de Espera quando quem pôs
        lá foi o operador (motivo dele, não "frota insuficiente").
        """
        ids: set[str] = set()
        for itens in list(self.itens_por_veiculo.values()) + list(self.itens_retorno_por_veiculo.values()):
            ids.update(self._id_item_de(i) for i in itens)
        for lista in (self.backlog_local, self.coletas):
            ids.update(self._id_item_de(b) for b in lista)
        for b in self.backlog:
            if b.get("motivo") not in self.MOTIVOS_DO_SISTEMA:
                ids.add(self._id_item_de(b))
        return ids

    def marcar_nao_saiu(self, veiculo_id: str, nao_saiu: bool = True) -> tuple[bool, str]:
        nome = next((r.veiculo_nome for r in self.rotas if r.veiculo_id == veiculo_id), veiculo_id)
        if nao_saiu and veiculo_id not in self.veiculos_nao_sairam:
            self.veiculos_nao_sairam.append(veiculo_id)
            if veiculo_id not in self.veiculos_fechados:
                self.veiculos_fechados.append(veiculo_id)
        if not nao_saiu and veiculo_id in self.veiculos_nao_sairam:
            self.veiculos_nao_sairam.remove(veiculo_id)
        if nao_saiu:
            return True, f"{nome} marcado como NÃO SAIU: a carga vai para a próxima rota."
        return True, f"{nome} voltou a contar como saído."

    def fechar_veiculo(self, veiculo_id: str, fechado: bool = True) -> tuple[bool, str]:
        nome = next((r.veiculo_nome for r in self.rotas if r.veiculo_id == veiculo_id), veiculo_id)
        if sum(1 for r in self.rotas if r.veiculo_nome == nome) > 1:
            nome = f"{nome} ({veiculo_id})"
        if fechado and veiculo_id not in self.veiculos_fechados:
            self.veiculos_fechados.append(veiculo_id)
        if not fechado and veiculo_id in self.veiculos_fechados:
            self.veiculos_fechados.remove(veiculo_id)
        return True, f"{nome} {'fechado: a sugestão automática não mexe mais nele' if fechado else 'reaberto'}."

    def sugerir_alocacao(
        self, consolidados: list[PedidoConsolidado], ativar_reserva: bool = False
    ) -> tuple[int, int]:
        """
        Sugestão INCREMENTAL: distribui só o que ainda não tem lugar (linhas
        novas, fila por frota insuficiente, pendências resolvidas), sem tirar
        nada do que o operador montou e sem tocar em caminhões fechados.
        Retorna (linhas alocadas agora, linhas que ficaram na fila).
        """
        self.params = carregar_parametros()
        self._cache_mapa_corredor = {}

        # Estado "ideal" das linhas: rota / pendência / entrega local.
        base = MotorLogistica(self.params)
        base._cache_mapa_corredor = {}
        roteaveis = base.carregar_pedidos(consolidados)
        no_quadro = self._ids_item_no_quadro()

        # Pendências: entram as novas, saem as resolvidas (atualiza o motivo).
        pend_atuais = {self._id_item_de(b): b for b in base.backlog_futuro}
        self.backlog_futuro = [
            pend_atuais.get(self._id_item_de(b), b)
            for b in self.backlog_futuro
            if (self._id_item_de(b) in pend_atuais or b.get("tipo_backlog") != config.COD_BACKLOG_FUTURO)
            and self._id_item_de(b) not in no_quadro  # operador já pôs num caminhão: respeita
        ]
        ja_futuro = {self._id_item_de(b) for b in self.backlog_futuro}
        for id_item, b in pend_atuais.items():
            if id_item not in ja_futuro and id_item not in no_quadro:
                self.backlog_futuro.append(b)
        locais = {self._id_item_de(b) for b in self.backlog_local}
        for b in base.backlog_local:
            if self._id_item_de(b) not in locais and self._id_item_de(b) not in no_quadro:
                self.backlog_local.append(b)

        # Candidatas: roteáveis que ainda não têm lugar no quadro.
        veiculos_ordem = self._ordem_veiculos(ativar_reserva)
        candidatas = [
            p for p in self._dividir_excedentes(roteaveis, veiculos_ordem)
            if self._id_item_de(p) not in no_quadro
        ]
        ids_candidatas = {self._id_item_de(p) for p in candidatas}
        self.backlog = [b for b in self.backlog if self._id_item_de(b) not in ids_candidatas]

        clusters = self._agrupar_por_rota(candidatas)
        alocados: set[str] = set()
        for vid, vinfo in veiculos_ordem:
            if vid in self.veiculos_fechados:
                continue
            atuais = self._itens_veiculo_como_dicts(vid)
            estado = EstadoVeiculo(
                veiculo_id=vid,
                veiculo_nome=vinfo.get("nome", vid),
                veiculo_tipo=vinfo.get("tipo", "BAU"),
                capacidade_kg=float(vinfo.get("capacidade_peso", 0)),
                itens=list(atuais),
                peso_alocado=sum(_float(i.get("peso_kg")) for i in atuais),
            )
            rota_existente = next((r for r in self.rotas if r.veiculo_id == vid), None)
            if atuais and rota_existente and rota_existente.rota_vocacao:
                estado.rota_vocacao = rota_existente.rota_vocacao
            else:
                ancora = self._escolher_ancora(clusters, estado, alocados)
                if not ancora:
                    continue
                self._alocar_item(estado, ancora)
                alocados.add(_cid(ancora))
                estado.rota_vocacao = ancora["rota_logistica"]
            for pedido in self._fila_priorizada(estado, clusters, alocados):
                if self.pode_alocar(pedido, estado)[0]:
                    self._alocar_item(estado, pedido)
                    alocados.add(_cid(pedido))

            novos = [i for i in estado.itens[len(atuais):]]
            if not novos:
                continue
            itens = self.itens_por_veiculo.setdefault(vid, [])
            itens.extend(self._dict_para_item(i, len(itens) + n) for n, i in enumerate(novos, 1))
            if not rota_existente:
                estado.regiao_predominante = rotulo_rota(estado.rota_vocacao)
                self.rotas.append(self._estado_para_rota(estado))
            self.recalcular_metricas(vid)

        sobras = [p for p in candidatas if _cid(p) not in alocados]
        for p in sobras:
            self.backlog.append(
                {
                    "numero_pedido": p["numero_pedido"],
                    "id_carga": _cid(p),
                    "id_item": p.get("id_item", ""),
                    "of_ano": p.get("of_ano", ""),
                    "obs_recebimento": p.get("obs_recebimento", ""),
                    "entrega_em": p.get("entrega_em", ""),
                    "entrega_cliente_codigo": p.get("entrega_cliente_codigo", ""),
                    "pendente_desde": p.get("pendente_desde", ""),
                    "data_producao": p.get("data_producao", ""),
                    "parte": str(p.get("parte", "")),
                    "divisao_automatica": str(p.get("divisao_automatica", "") or ""),
                    "peso_total_linha": str(p.get("peso_total_linha", "") or ""),
                    "cliente": p["cliente"],
                    "cliente_codigo": p.get("cliente_codigo", ""),
                    "representante": p.get("representante", ""),
                    "cidade_destino": p.get("cidade_destino", ""),
                    "rota_logistica": p.get("rota_logistica", ""),
                    "peso_kg": str(p["peso_kg"]),
                    "motivo": config.COD_FROTA_INSUFICIENTE,
                }
            )
        self._calcular_oportunidades()
        return len(alocados), len(sobras)

    def incluir_linhas_novas(self, consolidados_novos: list[PedidoConsolidado]) -> int:
        """
        Uma lista nova chegou no mesmo dia (ex.: a de solda/cerca/esponja, ou um
        adicional). As linhas entram no quadro SEM mexer no que já está montado:
        pendências em "Parados", entregas locais na fila local e o resto na Fila
        de Espera como "nova linha". O operador arrasta ou usa "Sugerir alocação".
        """
        base = MotorLogistica(self.params)
        base._cache_mapa_corredor = {}
        roteaveis = base.carregar_pedidos(consolidados_novos)
        self.backlog_futuro.extend(base.backlog_futuro)
        self.backlog_local.extend(base.backlog_local)
        partes = self._dividir_excedentes(roteaveis, self._ordem_veiculos(False))
        for p in partes:
            self.backlog.append(
                {
                    "numero_pedido": p["numero_pedido"],
                    "id_carga": _cid(p),
                    "id_item": p.get("id_item", ""),
                    "of_ano": p.get("of_ano", ""),
                    "obs_recebimento": p.get("obs_recebimento", ""),
                    "entrega_em": p.get("entrega_em", ""),
                    "entrega_cliente_codigo": p.get("entrega_cliente_codigo", ""),
                    "pendente_desde": p.get("pendente_desde", ""),
                    "data_producao": p.get("data_producao", ""),
                    "parte": str(p.get("parte", "")),
                    "divisao_automatica": str(p.get("divisao_automatica", "") or ""),
                    "peso_total_linha": str(p.get("peso_total_linha", "") or ""),
                    "cliente": p["cliente"],
                    "cliente_codigo": p.get("cliente_codigo", ""),
                    "representante": p.get("representante", ""),
                    "cidade_destino": p.get("cidade_destino", ""),
                    "rota_logistica": p.get("rota_logistica", ""),
                    "peso_kg": str(p["peso_kg"]),
                    "motivo": self.MOTIVO_NOVA_LINHA,
                }
            )
        return len(base.backlog_futuro) + len(base.backlog_local) + len(partes)

    def aplicar_sequencia(self, veiculo_id: str, ordem_paradas: list[str]) -> None:
        """
        Reordena o caminhão pela ordem de PARADAS (chave cliente|cidade) e
        renumera a sequência de entrega (1 = primeira entrega).
        """
        itens = self.itens_por_veiculo.get(veiculo_id, [])
        posicao = {chave: i for i, chave in enumerate(ordem_paradas)}
        chave = lambda it: f"{it.cliente_codigo}|{it.cidade_destino}".upper()  # noqa: E731
        itens.sort(key=lambda it: posicao.get(chave(it), len(posicao)))
        for seq, it in enumerate(itens, 1):
            it.sequencia_lifo = str(seq)
        self.itens_por_veiculo[veiculo_id] = itens

    def assinatura_carga(self, veiculo_id: str) -> str:
        """Ids das cargas do caminhão na ordem de entrega (muda se mexer na carga ou na ordem)."""
        return "|".join(_cid(it) for it in self.itens_por_veiculo.get(veiculo_id, []))

    def ordem_otimizada(self, veiculo_id: str) -> bool:
        itens = self.itens_por_veiculo.get(veiculo_id, [])
        if len({f"{it.cliente_codigo}|{it.cidade_destino}".upper() for it in itens}) < 2:
            return True  # 0 ou 1 parada: não há ordem para otimizar
        return self.sequencia_otimizada.get(veiculo_id) == self.assinatura_carga(veiculo_id)

    def sugestao_corredor(self, veiculo_id: str, nomes: dict[str, str] | None = None) -> dict[str, Any]:
        """
        Caminhão com corredores misturados: quem é o "intruso" e para qual caminhão
        aberto (do mesmo corredor do intruso) ele pode ir.
        """
        itens = [asdict(i) for i in self.itens_por_veiculo.get(veiculo_id, [])]
        por_corredor: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for it in itens:
            c = self._corredor_pedido(it)
            if c is not None:
                por_corredor[c].append(it)
        if len(por_corredor) <= 1:
            return {"texto": "", "ids": [], "destino": ""}
        menor = min(por_corredor, key=lambda c: (sum(_float(i.get("peso_kg")) for i in por_corredor[c]),
                                                  len(por_corredor[c])))
        intrusos = por_corredor[menor]
        apelidos = list(dict.fromkeys(self._apelido_cliente(str(i.get("cliente") or "")) for i in intrusos))
        peso = sum(_float(i.get("peso_kg")) for i in intrusos)
        nomes = nomes or {}
        rotas = {r.veiculo_id: r for r in self.rotas}
        for vid, outros in self.itens_por_veiculo.items():
            if vid == veiculo_id or vid in self.veiculos_fechados or vid in self.veiculos_nao_sairam:
                continue
            dom = self._corredor_dominante([asdict(o) for o in outros]) if outros else None
            rota = rotas.get(vid)
            folga = (rota.capacidade_kg - rota.peso_alocado_kg) if rota else 0
            if dom == menor and folga >= peso:
                return {
                    "texto": f"Sugestão: passar {', '.join(apelidos)} para {nomes.get(vid, vid)}",
                    "ids": [_cid(i) for i in intrusos],
                    "destino": vid,
                }
        return {
            "texto": f"{', '.join(apelidos)} ({self._nome_corredor(menor)}) está fora do corredor deste caminhão",
            "ids": [],
            "destino": "",
        }

    def tirar_do_caminhao_por_pendencia(self, id_item: str, motivo: str) -> str:
        """
        A linha voltou a ter pendência (ex.: desfez a liberação): sai do caminhão
        e vai para "Parados" com o motivo. Retorna o nome do caminhão ou "".
        """
        nomes = {r.veiculo_id: r.veiculo_nome for r in self.rotas}
        saiu_de = ""
        for vid in list(self.itens_por_veiculo.keys()):
            ficam = []
            for item in self.itens_por_veiculo[vid]:
                if self._id_item_de(item) == id_item:
                    d = asdict(item)
                    self.backlog_futuro.append(
                        {
                            **{k: str(v) for k, v in self._backlog_para_pedido(
                                {k2: str(v2) for k2, v2 in d.items()}
                            ).items()},
                            "motivo": motivo,
                            "tipo_backlog": config.COD_BACKLOG_FUTURO,
                        }
                    )
                    saiu_de = nomes.get(vid, vid)
                else:
                    ficam.append(item)
            if len(ficam) != len(self.itens_por_veiculo[vid]):
                self.itens_por_veiculo[vid] = ficam
                self.recalcular_metricas(vid)
        return saiu_de

    def _dividir_excedentes(
        self,
        pedidos: list[dict[str, Any]],
        veiculos_ordem: list[tuple[str, dict]],
    ) -> list[dict[str, Any]]:
        """
        Divide por peso as linhas que não cabem inteiras em nenhum caminhão.

        Ex.: 10 t com caminhões de no máximo 6 t -> 2 partes de 5 t. As partes
        são iguais (o operador ajusta depois com "Dividir carga" no Kanban) e
        herdam as restrições da linha (SYDER, dimensão longa...).
        """
        caps_todos = [float(v.get("capacidade_peso", 0)) for _, v in veiculos_ordem]
        caps_syder = [
            float(v.get("capacidade_peso", 0)) for _, v in veiculos_ordem if v.get("tipo") == "SYDER"
        ]
        resultado: list[dict[str, Any]] = []
        for p in pedidos:
            exige_syder = p.get("exige_syder") == "SIM" or p.get("is_dimensao_longa") == "SIM"
            caps = caps_syder if exige_syder else caps_todos
            cap_max = max(caps) if caps else 0.0
            peso = _float(p.get("peso_kg"))
            if cap_max <= 0 or peso <= cap_max:
                resultado.append(p)
                continue
            n_partes = int(-(-peso // cap_max))  # teto
            base = round(peso / n_partes, 1)
            id_item = p.get("id_item") or _cid(p)
            for n in range(1, n_partes + 1):
                parte = dict(p)
                parte["peso_kg"] = base if n < n_partes else round(peso - base * (n_partes - 1), 1)
                parte["id_carga"] = _id_parte(id_item, n)
                parte["id_item"] = id_item
                parte["parte"] = f"{n}/{n_partes}"
                parte["peso_total_linha"] = peso
                # Sugestão: o operador confere e faz o ajuste fino no Kanban.
                parte["divisao_automatica"] = "SIM"
                resultado.append(parte)
        return resultado

    def _localizar_carga(self, id_carga: str) -> tuple[str, Any] | None:
        """Retorna (coluna, objeto) da carga: ItemRota nos veículos, dict nos backlogs."""
        for vid, itens in self.itens_por_veiculo.items():
            for item in itens:
                if _mesma_carga(item, id_carga):
                    return vid, item
        for vid, itens in self.itens_retorno_por_veiculo.items():
            for item in itens:
                if _mesma_carga(item, id_carga):
                    return self._id_retorno(vid), item
        for nome, lista in (
            ("BACKLOG", self.backlog),
            (config.COD_BACKLOG_FUTURO, self.backlog_futuro),
            (config.COD_BACKLOG_LOCAL, self.backlog_local),
            ("COLETAS", self.coletas),
        ):
            for entry in lista:
                if _mesma_carga(entry, id_carga):
                    return nome, entry
        return None

    def _todas_as_cargas(self) -> list[Any]:
        cargas: list[Any] = []
        for itens in list(self.itens_por_veiculo.values()) + list(self.itens_retorno_por_veiculo.values()):
            cargas.extend(itens)
        for lista in (self.backlog, self.backlog_futuro, self.backlog_local, self.coletas):
            cargas.extend(lista)
        return cargas

    def dividir_carga(self, id_carga: str, peso_nova_parte: float) -> tuple[bool, str]:
        """
        Divide uma carga em duas, por peso. A nova parte fica na MESMA coluna;
        o operador arrasta para outro caminhão. Pode ser repetido (3, 4 partes...).
        """
        achado = self._localizar_carga(id_carga)
        if not achado:
            return False, f"Carga {id_carga} não encontrada."
        coluna, obj = achado
        eh_dict = isinstance(obj, dict)
        peso_atual = _float(obj.get("peso_kg") if eh_dict else obj.peso_kg)
        peso_nova_parte = round(float(peso_nova_parte), 1)
        if peso_nova_parte <= 0 or peso_nova_parte >= peso_atual:
            return False, (
                f"Informe um peso entre 0 e {formatar_kg(peso_atual)} kg (peso atual desta carga)."
            )

        get = obj.get if eh_dict else (lambda k, d="": getattr(obj, k, d))
        id_item = get("id_item", "") or _cid(obj).split("@P")[0]
        irmas = [c for c in self._todas_as_cargas() if (
            (c.get("id_item") if isinstance(c, dict) else c.id_item) == id_item
        )]
        total = sum(_float(c.get("peso_kg") if isinstance(c, dict) else c.peso_kg) for c in irmas) or peso_atual
        usados = {_cid(c) for c in irmas}
        n = 1
        while _id_parte(id_item, n) in usados:
            n += 1
        # A carga original também passa a ser uma "parte" se ainda não era.
        if "@P" not in _cid(obj):
            novo_id_original = _id_parte(id_item, n)
            n += 1
            if eh_dict:
                obj["id_carga"] = novo_id_original
            else:
                obj.id_carga = novo_id_original
        id_nova = _id_parte(id_item, n)

        restante = round(peso_atual - peso_nova_parte, 1)
        if eh_dict:
            nova = dict(obj)
            obj["peso_kg"] = str(restante)
            nova["peso_kg"] = str(peso_nova_parte)
            nova["id_carga"] = id_nova
            nova["id_item"] = id_item
            lista = {
                "BACKLOG": self.backlog,
                config.COD_BACKLOG_FUTURO: self.backlog_futuro,
                config.COD_BACKLOG_LOCAL: self.backlog_local,
                "COLETAS": self.coletas,
            }[coluna]
            lista.append(nova)
        else:
            obj.peso_kg = restante
            nova = ItemRota(**{**asdict(obj), "peso_kg": peso_nova_parte, "id_carga": id_nova, "id_item": id_item})
            retorno_vid = self._parse_retorno_destino(coluna)
            if retorno_vid:
                self.itens_retorno_por_veiculo[retorno_vid].append(nova)
                self.recalcular_metricas_retorno(retorno_vid)
            else:
                self.itens_por_veiculo[coluna].append(nova)
                self.recalcular_metricas(coluna)

        self._renumerar_partes(id_item, total)
        self._marcar_conferida(id_item)
        return True, (
            f"Carga dividida: {formatar_kg(restante)} kg + {formatar_kg(peso_nova_parte)} kg. "
            "Arraste a nova parte para outro caminhão."
        )

    # ---- utilitários para cargas que podem ser ItemRota (veículo) ou dict (backlogs)
    @staticmethod
    def _peso(obj: Any) -> float:
        return _float(obj.get("peso_kg") if isinstance(obj, dict) else obj.peso_kg)

    @staticmethod
    def _set(obj: Any, campo: str, valor: Any) -> None:
        if isinstance(obj, dict):
            obj[campo] = str(valor)
        else:
            setattr(obj, campo, valor)

    @staticmethod
    def _id_item_de(obj: Any) -> str:
        valor = obj.get("id_item") if isinstance(obj, dict) else obj.id_item
        return valor or _cid(obj).split("@P")[0]

    def _partes_da_linha(self, id_item: str) -> list[tuple[str, Any]]:
        partes: list[tuple[str, Any]] = []
        for c in self._todas_as_cargas():
            if self._id_item_de(c) == id_item:
                achado = self._localizar_carga(_cid(c))
                if achado:
                    partes.append(achado)
        return partes

    def _remover_carga(self, coluna: str, obj: Any) -> None:
        listas = {
            "BACKLOG": self.backlog,
            config.COD_BACKLOG_FUTURO: self.backlog_futuro,
            config.COD_BACKLOG_LOCAL: self.backlog_local,
            "COLETAS": self.coletas,
        }
        if coluna in listas:
            listas[coluna][:] = [x for x in listas[coluna] if x is not obj]
            return
        retorno_vid = self._parse_retorno_destino(coluna)
        if retorno_vid:
            self.itens_retorno_por_veiculo[retorno_vid] = [
                x for x in self.itens_retorno_por_veiculo[retorno_vid] if x is not obj
            ]
            self.recalcular_metricas_retorno(retorno_vid)
        else:
            self.itens_por_veiculo[coluna] = [x for x in self.itens_por_veiculo[coluna] if x is not obj]
            self.recalcular_metricas(coluna)

    def _recalcular_coluna(self, coluna: str) -> None:
        retorno_vid = self._parse_retorno_destino(coluna)
        if retorno_vid:
            self.recalcular_metricas_retorno(retorno_vid)
        elif coluna in self.itens_por_veiculo:
            self.recalcular_metricas(coluna)

    def _aviso_capacidade(self, colunas: set[str]) -> str:
        avisos = []
        for rota in self.rotas:
            if rota.veiculo_id in colunas and rota.capacidade_kg and rota.peso_alocado_kg > rota.capacidade_kg:
                excesso = rota.peso_alocado_kg - rota.capacidade_kg
                avisos.append(f"{rota.veiculo_nome} passou {formatar_kg(excesso)} kg da capacidade")
        return " | ".join(avisos)

    def _marcar_conferida(self, id_item: str) -> None:
        for _, obj in self._partes_da_linha(id_item):
            self._set(obj, "divisao_automatica", "")

    def ajustar_divisao(
        self, id_carga: str, peso_desejado: float, id_contrapartida: str = ""
    ) -> tuple[bool, str]:
        """
        Ajuste fino: ESTA parte passa a ter `peso_desejado` e a diferença sai/entra
        na contrapartida (outra parte da mesma linha). Ex.: BAÚ 1 leva 5.322 kg e o
        restante fica no outro card. O peso total da linha não muda.
        """
        achado = self._localizar_carga(id_carga)
        if not achado:
            return False, f"Carga {id_carga} não encontrada."
        coluna, obj = achado
        id_item = self._id_item_de(obj)
        outras = [(c, o) for c, o in self._partes_da_linha(id_item) if o is not obj]
        if not outras:
            return False, "Esta carga não está dividida. Use “Dividir carga” primeiro."
        if id_contrapartida:
            contra = next(((c, o) for c, o in outras if _cid(o) == id_contrapartida), None)
            if not contra:
                return False, "A outra parte escolhida não pertence a esta linha."
        else:
            contra = max(outras, key=lambda co: self._peso(co[1]))
        coluna_contra, obj_contra = contra

        peso_desejado = round(float(peso_desejado), 1)
        atual, atual_contra = self._peso(obj), self._peso(obj_contra)
        limite = round(atual + atual_contra, 1)
        if peso_desejado <= 0 or peso_desejado > limite:
            return False, f"Informe um peso entre 0 e {formatar_kg(limite)} kg."

        novo_contra = round(limite - peso_desejado, 1)
        self._set(obj, "peso_kg", peso_desejado)
        total = sum(self._peso(o) for _, o in self._partes_da_linha(id_item))
        if novo_contra <= 0:
            self._remover_carga(coluna_contra, obj_contra)
        else:
            self._set(obj_contra, "peso_kg", novo_contra)
            self._recalcular_coluna(coluna_contra)
        self._recalcular_coluna(coluna)
        self._renumerar_partes(id_item, total)
        self._marcar_conferida(id_item)

        msg = (
            f"Ajustado: {formatar_kg(peso_desejado)} kg nesta carga"
            + (f" e {formatar_kg(novo_contra)} kg na outra parte." if novo_contra > 0 else "; a outra parte foi absorvida.")
        )
        aviso = self._aviso_capacidade({coluna, coluna_contra})
        return True, f"{msg} ATENÇÃO: {aviso}" if aviso else msg

    def juntar_partes(self, id_carga: str) -> tuple[bool, str]:
        """Desfaz a divisão: todas as partes da linha voltam para ESTE card."""
        achado = self._localizar_carga(id_carga)
        if not achado:
            return False, f"Carga {id_carga} não encontrada."
        coluna, obj = achado
        id_item = self._id_item_de(obj)
        outras = [(c, o) for c, o in self._partes_da_linha(id_item) if o is not obj]
        if not outras:
            return False, "Esta carga não está dividida."
        total = self._peso(obj) + sum(self._peso(o) for _, o in outras)
        for c, o in outras:
            self._remover_carga(c, o)
        self._set(obj, "peso_kg", round(total, 1))
        self._set(obj, "id_carga", id_item)
        self._set(obj, "parte", "")
        self._set(obj, "divisao_automatica", "")
        self._recalcular_coluna(coluna)
        msg = f"Partes juntadas: {formatar_kg(total)} kg neste card."
        aviso = self._aviso_capacidade({coluna})
        return True, f"{msg} ATENÇÃO: {aviso}" if aviso else msg

    def confirmar_divisao(self, id_carga: str) -> tuple[bool, str]:
        """Operador conferiu a divisão automática e concorda com ela."""
        achado = self._localizar_carga(id_carga)
        if not achado:
            return False, f"Carga {id_carga} não encontrada."
        self._marcar_conferida(self._id_item_de(achado[1]))
        return True, "Divisão conferida."

    def _renumerar_partes(self, id_item: str, total: float) -> None:
        partes = [
            c for c in self._todas_as_cargas()
            if (c.get("id_item") if isinstance(c, dict) else c.id_item) == id_item
        ]
        partes.sort(key=lambda c: _cid(c))
        for i, c in enumerate(partes, 1):
            rotulo = f"{i}/{len(partes)}" if len(partes) > 1 else ""
            if isinstance(c, dict):
                c["parte"] = rotulo
                c["peso_total_linha"] = str(total)
            else:
                c.parte = rotulo
                c.peso_total_linha = total

    def pode_alocar(
        self, pedido: dict[str, Any], estado: EstadoVeiculo
    ) -> tuple[bool, str]:
        if estado.peso_alocado + pedido["peso_kg"] > estado.capacidade_kg:
            return False, config.COD_FROTA_INSUFICIENTE

        if pedido.get("exige_syder") == "SIM" and estado.veiculo_tipo != "SYDER":
            return False, "EXIGE SYDER"

        if pedido.get("is_dimensao_longa") == "SIM" and estado.veiculo_tipo != "SYDER":
            return False, "DIMENSÃO LONGA — SOMENTE SYDER"

        if estado.veiculo_tipo == "BAU" and estado.veiculo_id == "VAN_MASTER":
            if pedido.get("is_dimensao_longa") == "SIM":
                return False, "BLOQUEIO VAN MASTER"

        tempo = self.calcular_tempo_rota(estado.itens + [pedido])
        jornada_max = int(self.params.get("jornada_maxima_minutos", 600))
        if tempo > jornada_max:
            return False, config.COD_LIMITE_JORNADA

        return True, "OK"

    def calcular_tempo_rota(self, itens: list[dict[str, Any]]) -> int:
        """
        Tempo total da rota (minutos) — ÚNICO cálculo do sistema: é o que o motor
        usa para decidir se cabe na jornada E o que aparece no card (TEO).

        = ida e volta até a cidade mais distante
        + deslocamento entre cidades (por cidade extra no caminho)
        + descarga por parada (cliente/cidade)
        + almoço
        """
        if not itens:
            return 0
        cidades = {
            normalizar_texto(i.get("cidade_destino", "")).replace("'", " ")
            for i in itens
            if i.get("cidade_destino")
        }
        if cidades:
            viagem = max(self._tempo_viagem_cidade(c) for c in cidades)
        else:
            tempos_map = self.params.get("tempos_viagem_rota_min", {})
            viagem = max(
                int(tempos_map.get(i.get("rota_logistica", "ROTA_OUTROS"), tempos_map.get("ROTA_OUTROS", 300)))
                for i in itens
            )
        entre_cidades = int(self.params.get("tempo_entre_cidades_min", 20)) * max(len(cidades) - 1, 0)
        descarga = int(self.params.get("tempo_descarga_minutos", config.TEMPO_DESCARGA_MINUTOS))
        almoco = int(self.params.get("tempo_almoco_minutos", 60))
        return viagem + entre_cidades + self._contar_paradas_unicas(itens) * descarga + almoco

    @staticmethod
    def _contar_paradas_unicas(itens: list[dict[str, Any]]) -> int:
        chaves: set[str] = set()
        for item in itens:
            chave = f"{item.get('cliente_codigo', '')}|{item.get('cidade_destino', '')}".upper()
            chaves.add(chave)
        return len(chaves)

    def _horario_inicio(self) -> str:
        return str(self.params.get("inicio_expediente", "07:00"))

    def _agrupar_por_rota(
        self, pedidos: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        clusters: dict[str, list[dict[str, Any]]] = {}
        for p in sorted(pedidos, key=lambda x: x["peso_kg"], reverse=True):
            rota = p["rota_logistica"]
            clusters.setdefault(rota, []).append(p)
        return dict(
            sorted(clusters.items(), key=lambda kv: sum(i["peso_kg"] for i in kv[1]), reverse=True)
        )

    def _ordem_veiculos(self, ativar_reserva: bool) -> list[tuple[str, dict]]:
        veiculos = self.params.get("veiculos", {})
        ordem_ids = list(self.params.get("ordem_veiculos", []))
        if not ordem_ids:
            ordem_ids = list(veiculos.keys())
        if ativar_reserva and "VAN_MASTER" in veiculos and "VAN_MASTER" not in ordem_ids:
            ordem_ids.append("VAN_MASTER")

        resultado: list[tuple[str, dict]] = []
        for vid in ordem_ids:
            v = veiculos.get(vid)
            if not v:
                continue
            if v.get("disponivel", False):
                resultado.append((vid, v))
            elif vid == "VAN_MASTER" and ativar_reserva:
                resultado.append((vid, v))
        return resultado

    def _escolher_ancora(
        self,
        clusters: dict[str, list[dict[str, Any]]],
        estado: EstadoVeiculo,
        alocados_ids: set[str],
    ) -> dict[str, Any] | None:
        candidatos: list[dict[str, Any]] = []
        for lista in clusters.values():
            for pedido in lista:
                if _cid(pedido) in alocados_ids:
                    continue
                ok, _ = self.pode_alocar(pedido, estado)
                if ok:
                    candidatos.append(pedido)

        if not candidatos:
            return None

        corredor_alvo = self._corredor_dominante(estado.itens)
        if corredor_alvo is None and not estado.itens:
            peso_por_corredor: dict[int, float] = defaultdict(float)
            for pedido in candidatos:
                corredor = self._corredor_pedido(pedido)
                if corredor is not None:
                    peso_por_corredor[corredor] += float(pedido.get("peso_kg") or 0)
            if peso_por_corredor:
                corredor_alvo = max(peso_por_corredor, key=peso_por_corredor.get)

        def chave_ancora(pedido: dict[str, Any]) -> tuple[int, float]:
            corredor = self._corredor_pedido(pedido)
            mesmo_corredor = 0 if corredor_alvo is not None and corredor == corredor_alvo else 1
            return (mesmo_corredor, -float(pedido.get("peso_kg") or 0))

        candidatos.sort(key=chave_ancora)
        return candidatos[0]

    def _fila_priorizada(
        self,
        estado: EstadoVeiculo,
        clusters: dict[str, list[dict[str, Any]]],
        alocados_ids: set[str],
    ) -> list[dict[str, Any]]:
        corredor_alvo = self._corredor_dominante(estado.itens)
        vizinhas_raw = self.params.get("rotas_vizinhas", {}).get(estado.rota_vocacao, "")
        vizinhas = {v.strip() for v in vizinhas_raw.split(",") if v.strip()}
        rotas_ok = {estado.rota_vocacao} | vizinhas

        fila: list[dict[str, Any]] = []
        vistos: set[str] = set()

        if corredor_alvo is not None:
            for lista in clusters.values():
                for pedido in lista:
                    pid = _cid(pedido)
                    if pid in alocados_ids or pid in vistos:
                        continue
                    if self._corredor_pedido(pedido) == corredor_alvo:
                        fila.append(pedido)
                        vistos.add(pid)

        for rota in rotas_ok:
            for pedido in clusters.get(rota, []):
                pid = _cid(pedido)
                if pid in alocados_ids or pid in vistos:
                    continue
                fila.append(pedido)
                vistos.add(pid)

        def chave_fila(pedido: dict[str, Any]) -> tuple[int, float]:
            corredor = self._corredor_pedido(pedido)
            mesmo_corredor = 0 if corredor_alvo is not None and corredor == corredor_alvo else 1
            return (mesmo_corredor, -float(pedido.get("peso_kg") or 0))

        return sorted(fila, key=chave_fila)

    @staticmethod
    def _alocar_item(estado: EstadoVeiculo, pedido: dict[str, Any]) -> None:
        estado.itens.append(pedido)
        estado.peso_alocado += pedido["peso_kg"]

    def _estado_para_rota(self, estado: EstadoVeiculo) -> RotaVeiculo:
        tempo_min = self.calcular_tempo_rota(estado.itens)
        paradas = self._contar_paradas_unicas(estado.itens)
        eficiencia = (
            (estado.peso_alocado / estado.capacidade_kg * 100) if estado.capacidade_kg else 0
        )

        inicio = datetime.strptime(self._horario_inicio(), "%H:%M")
        retorno = inicio + timedelta(minutes=tempo_min)

        pedidos_csv = ", ".join(i["numero_pedido"] for i in estado.itens)

        rota = RotaVeiculo(
            veiculo_id=estado.veiculo_id,
            veiculo_nome=estado.veiculo_nome,
            regiao_predominante=estado.regiao_predominante,
            rota_vocacao=estado.rota_vocacao,
            capacidade_kg=estado.capacidade_kg,
            peso_alocado_kg=estado.peso_alocado,
            eficiencia_pct=f"{eficiencia:.0f}%",
            tempo_total_min=str(tempo_min),
            retorno_previsto=retorno.strftime("%H:%M"),
            qtd_paradas=str(paradas),
            pedidos_csv=pedidos_csv,
        )
        self._aplicar_alertas_rota(rota, estado.itens)
        return rota

    @staticmethod
    def _dict_para_item(pedido: dict[str, Any], sequencia: int) -> ItemRota:
        return ItemRota(
            numero_pedido=pedido["numero_pedido"],
            id_carga=_cid(pedido),
            id_item=str(pedido.get("id_item", "")),
            of_ano=str(pedido.get("of_ano", "")),
            parte=str(pedido.get("parte", "") or ""),
            divisao_automatica=str(pedido.get("divisao_automatica", "") or ""),
            obs_recebimento=str(pedido.get("obs_recebimento", "") or ""),
            entrega_em=str(pedido.get("entrega_em", "") or ""),
            entrega_cliente_codigo=str(pedido.get("entrega_cliente_codigo", "") or ""),
            pendente_desde=str(pedido.get("pendente_desde", "") or ""),
            data_producao=str(pedido.get("data_producao", "") or ""),
            peso_total_linha=_float(pedido.get("peso_total_linha")),
            cliente=pedido["cliente"],
            cliente_codigo=pedido.get("cliente_codigo", ""),
            representante=pedido.get("representante", ""),
            bairro_destino=pedido.get("bairro_destino", ""),
            cidade_destino=pedido.get("cidade_destino", ""),
            estado_destino=pedido.get("estado_destino", ""),
            cep_destino=pedido.get("cep_destino", ""),
            rota_logistica=pedido.get("rota_logistica", ""),
            peso_kg=pedido["peso_kg"],
            sequencia_lifo=str(sequencia),
            is_spyder=pedido.get("is_spyder", "NAO"),
            is_dimensao_longa=pedido.get("is_dimensao_longa", "NAO"),
            exige_syder=pedido.get("exige_syder", "NAO"),
            enriquecido_mestre=pedido.get("enriquecido_mestre", "NAO"),
        )

    def _rotas_proximas(self, rota_a: str, rota_b: str) -> bool:
        if not rota_a or not rota_b:
            return False
        if rota_a == rota_b:
            return True
        vizinhas = self.params.get("rotas_vizinhas", {})
        viz_a = {v.strip() for v in str(vizinhas.get(rota_a, "")).split(",") if v.strip()}
        viz_b = {v.strip() for v in str(vizinhas.get(rota_b, "")).split(",") if v.strip()}
        return rota_b in viz_a or rota_a in viz_b

    def _calcular_oportunidades(self) -> None:
        from datetime import date as date_cls

        hoje_pt = date_cls.today().strftime("%d/%m/%Y")
        for item in self.backlog_futuro:
            # Parado por pendência (representante/comercial/peso): quem destrava é
            # a pessoa responsável, não uma "antecipação" — sem dica de oportunidade.
            if (item.get("aceita_antecipacao") or "SIM").upper() == "NAO" or item.get("pendencias"):
                for k in ("oportunidade", "oportunidade_dica", "oportunidade_veiculo_id", "oportunidade_veiculo_nome"):
                    item.pop(k, None)
                continue

            pedido_rota = item.get("rota_logistica", "")
            melhor = None
            for rota_veic in self.rotas:
                vocacao = rota_veic.rota_vocacao
                if vocacao and self._rotas_proximas(pedido_rota, vocacao):
                    melhor = rota_veic
                    break

            if melhor:
                cidade = item.get("cidade_destino", "")
                item["oportunidade"] = "SIM"
                item["oportunidade_dica"] = (
                    f"Caminhão passando perto de {cidade} em {hoje_pt}. Antecipar?"
                )
                item["oportunidade_veiculo_id"] = melhor.veiculo_id
                item["oportunidade_veiculo_nome"] = melhor.veiculo_nome
            else:
                for k in ("oportunidade", "oportunidade_dica", "oportunidade_veiculo_id", "oportunidade_veiculo_nome"):
                    item.pop(k, None)

    def para_dict(self) -> dict[str, Any]:
        metricas_retorno: dict[str, dict[str, Any]] = {}
        for vid, itens in self.itens_retorno_por_veiculo.items():
            dicts = [asdict(i) for i in itens]
            teo = self.calcular_teo(dicts)
            metricas_retorno[vid] = {
                "teo_minutos": str(teo),
                "teo_hhmm": self._format_hhmm(teo),
                "peso_alocado_kg": sum(i.peso_kg for i in itens),
                "qtd_pedidos": str(len(itens)),
            }

        return {
            "rotas": [asdict(r) for r in self.rotas],
            "itens_por_veiculo": {
                vid: [asdict(i) for i in itens]
                for vid, itens in self.itens_por_veiculo.items()
            },
            "backlog": self.backlog,
            "backlog_futuro": self.backlog_futuro,
            "backlog_local": self.backlog_local,
            "coletas": self.coletas,
            "itens_retorno_por_veiculo": {
                vid: [asdict(i) for i in itens]
                for vid, itens in self.itens_retorno_por_veiculo.items()
            },
            "viagens_retorno_habilitadas": list(self.viagens_retorno_habilitadas),
            "veiculos_fechados": list(self.veiculos_fechados),
            "veiculos_nao_sairam": list(self.veiculos_nao_sairam),
            "equipe_por_veiculo": dict(self.equipe_por_veiculo),
            "sequencia_otimizada": dict(self.sequencia_otimizada),
            "agenda": dict(self.agenda),
            "metricas_retorno": metricas_retorno,
        }

    def _itens_veiculo_como_dicts(self, veiculo_id: str) -> list[dict[str, Any]]:
        return [asdict(i) for i in self.itens_por_veiculo.get(veiculo_id, [])]

    def recalcular_regiao(self, veiculo_id: str) -> str:
        itens = self.itens_por_veiculo.get(veiculo_id, [])
        if not itens:
            for rota in self.rotas:
                if rota.veiculo_id == veiculo_id:
                    rota.regiao_predominante = ""
                    rota.rota_vocacao = ""
            return ""
        peso_por_rota: dict[str, float] = {}
        for item in itens:
            rota = item.rota_logistica or "ROTA_OUTROS"
            peso_por_rota[rota] = peso_por_rota.get(rota, 0) + item.peso_kg
        rota_dom = max(peso_por_rota, key=peso_por_rota.get)
        regiao = rotulo_rota(rota_dom)
        for rota in self.rotas:
            if rota.veiculo_id == veiculo_id:
                rota.regiao_predominante = regiao
                rota.rota_vocacao = rota_dom
        return regiao

    def recalcular_metricas(self, veiculo_id: str) -> None:
        """Recalcula peso, paradas únicas, jornada e retorno após movimentação manual."""
        itens = self.itens_por_veiculo.get(veiculo_id, [])
        dicts = self._itens_veiculo_como_dicts(veiculo_id)
        peso = sum(i.peso_kg for i in itens)
        paradas = self._contar_paradas_unicas(dicts)
        tempo_min = self.calcular_tempo_rota(dicts)

        inicio = datetime.strptime(self._horario_inicio(), "%H:%M")
        retorno = inicio + timedelta(minutes=tempo_min)

        for rota in self.rotas:
            if rota.veiculo_id != veiculo_id:
                continue
            rota.peso_alocado_kg = peso
            if rota.capacidade_kg > 0:
                rota.eficiencia_pct = f"{(peso / rota.capacidade_kg) * 100:.0f}%"
            rota.qtd_paradas = str(paradas)
            rota.tempo_total_min = str(tempo_min)
            rota.retorno_previsto = retorno.strftime("%H:%M") if dicts else ""
            rota.pedidos_csv = ", ".join(i.numero_pedido for i in itens)
            self._aplicar_alertas_rota(rota, dicts)
            if dicts:
                self.recalcular_regiao(veiculo_id)
            else:
                rota.regiao_predominante = ""
                rota.rota_vocacao = ""
                rota.teo_minutos = "0"
                rota.teo_hhmm = "0h00"
                rota.segunda_viagem_elegivel = True
                rota.alerta_elastico = False
                rota.mensagem_alerta_elastico = ""
            break

        for seq, item in enumerate(itens, 1):
            item.sequencia_lifo = str(seq)

    def recalcular_metricas_retorno(self, veiculo_id: str) -> None:
        itens = self.itens_retorno_por_veiculo.get(veiculo_id, [])
        for seq, item in enumerate(itens, 1):
            item.sequencia_lifo = str(seq)

    def habilitar_segunda_viagem(self, veiculo_id: str) -> tuple[bool, str]:
        destinos = {r.veiculo_id for r in self.rotas}
        if veiculo_id not in destinos:
            return False, f"Veículo inválido: {veiculo_id}"
        if veiculo_id not in self.viagens_retorno_habilitadas:
            self.viagens_retorno_habilitadas.append(veiculo_id)
        self.itens_retorno_por_veiculo.setdefault(veiculo_id, [])
        return True, ""

    def _validar_movimento_retorno(
        self,
        pedido_dict: dict[str, Any],
        veiculo_id: str,
    ) -> tuple[bool, str]:
        if veiculo_id not in self.viagens_retorno_habilitadas:
            return False, "2ª viagem não habilitada para este veículo."

        rota_meta = next((r for r in self.rotas if r.veiculo_id == veiculo_id), None)
        if not rota_meta:
            return False, f"Veículo destino inválido: {veiculo_id}"

        itens_atuais = [asdict(i) for i in self.itens_retorno_por_veiculo.get(veiculo_id, [])]
        peso_atual = sum(i.get("peso_kg", 0) for i in itens_atuais)
        if peso_atual + pedido_dict.get("peso_kg", 0) > rota_meta.capacidade_kg:
            return False, config.COD_FROTA_INSUFICIENTE

        veiculos = self.params.get("veiculos", {})
        vinfo = veiculos.get(veiculo_id, {})
        if pedido_dict.get("exige_syder") == "SIM" and vinfo.get("tipo", "BAU") != "SYDER":
            return False, "EXIGE SYDER"
        if pedido_dict.get("is_dimensao_longa") == "SIM" and vinfo.get("tipo", "BAU") != "SYDER":
            return False, "DIMENSÃO LONGA — SOMENTE SYDER"

        return True, "OK"

    def _validar_movimento_veiculo(
        self,
        pedido_dict: dict[str, Any],
        destino: str,
    ) -> tuple[bool, str]:
        """Valida peso, SPYDER e jornada antes de alocar manualmente."""
        itens_atuais = self._itens_veiculo_como_dicts(destino)
        rota_meta = next((r for r in self.rotas if r.veiculo_id == destino), None)
        if not rota_meta:
            return False, f"Veículo destino inválido: {destino}"

        veiculos = self.params.get("veiculos", {})
        vinfo = veiculos.get(destino, {})
        estado = EstadoVeiculo(
            veiculo_id=destino,
            veiculo_tipo=vinfo.get("tipo", "BAU"),
            capacidade_kg=rota_meta.capacidade_kg,
            itens=itens_atuais,
            peso_alocado=sum(i.get("peso_kg", 0) for i in itens_atuais),
        )
        return self.pode_alocar(pedido_dict, estado)

    def mover_pedido(
        self,
        numero_pedido: str,
        destino: str,
        motivo: str = "",
        forcar: bool = False,
    ) -> tuple[bool, str]:
        """Move pedido entre veículos, backlog ou coletas. Retorna (ok, warning)."""
        pedido_dict: dict[str, Any] | None = None
        origem: str | None = None

        for vid, itens in self.itens_por_veiculo.items():
            for i, item in enumerate(itens):
                if _mesma_carga(item, numero_pedido):
                    pedido_dict = asdict(item)
                    origem = vid
                    self.itens_por_veiculo[vid].pop(i)
                    break
            if pedido_dict:
                break

        if not pedido_dict:
            for i, b in enumerate(self.backlog_futuro):
                if _mesma_carga(b, numero_pedido):
                    pedido_dict = self._backlog_para_pedido(b)
                    self.backlog_futuro.pop(i)
                    origem = config.COD_BACKLOG_FUTURO
                    break

        if not pedido_dict:
            for vid, itens in self.itens_retorno_por_veiculo.items():
                for i, item in enumerate(itens):
                    if _mesma_carga(item, numero_pedido):
                        pedido_dict = asdict(item)
                        origem = self._id_retorno(vid)
                        self.itens_retorno_por_veiculo[vid].pop(i)
                        break
                if pedido_dict:
                    break

        if not pedido_dict:
            for i, b in enumerate(self.backlog_local):
                if _mesma_carga(b, numero_pedido):
                    pedido_dict = self._backlog_para_pedido(b)
                    self.backlog_local.pop(i)
                    origem = config.COD_BACKLOG_LOCAL
                    break

        if not pedido_dict:
            for i, b in enumerate(self.backlog):
                if _mesma_carga(b, numero_pedido):
                    pedido_dict = self._backlog_para_pedido(b)
                    self.backlog.pop(i)
                    origem = "BACKLOG"
                    break

        if not pedido_dict:
            for i, c in enumerate(self.coletas):
                if _mesma_carga(c, numero_pedido):
                    pedido_dict = self._backlog_para_pedido(c)
                    self.coletas.pop(i)
                    origem = "COLETAS"
                    break

        if not pedido_dict:
            return False, f"Pedido {numero_pedido} não encontrado."

        warning = ""
        destino_upper = destino.upper()
        colunas_especiais = {
            "BACKLOG",
            "COLETAS",
            config.COD_BACKLOG_FUTURO,
            config.COD_BACKLOG_LOCAL,
        }

        if destino_upper == "BACKLOG":
            self.backlog.append(
                {
                    "numero_pedido": pedido_dict.get("numero_pedido", ""),
                    "id_carga": _cid(pedido_dict),
                    "id_item": pedido_dict.get("id_item", ""),
                    "of_ano": pedido_dict.get("of_ano", ""),
                    "obs_recebimento": pedido_dict.get("obs_recebimento", ""),
                    "entrega_em": pedido_dict.get("entrega_em", ""),
                    "entrega_cliente_codigo": pedido_dict.get("entrega_cliente_codigo", ""),
                    "pendente_desde": pedido_dict.get("pendente_desde", ""),
                    "data_producao": pedido_dict.get("data_producao", ""),
                    "parte": str(pedido_dict.get("parte", "")),
                    "divisao_automatica": str(pedido_dict.get("divisao_automatica", "") or ""),
                    "peso_total_linha": str(pedido_dict.get("peso_total_linha", "") or ""),
                    "cliente": pedido_dict.get("cliente", ""),
                    "representante": pedido_dict.get("representante", ""),
                    "cidade_destino": pedido_dict.get("cidade_destino", ""),
                    "rota_logistica": pedido_dict.get("rota_logistica", ""),
                    "peso_kg": str(pedido_dict.get("peso_kg", 0)),
                    "motivo": motivo or "DECISAO OPERADOR",
                }
            )
        elif destino_upper == config.COD_BACKLOG_FUTURO:
            self.backlog_futuro.append(
                {
                    "numero_pedido": pedido_dict.get("numero_pedido", ""),
                    "id_carga": _cid(pedido_dict),
                    "id_item": pedido_dict.get("id_item", ""),
                    "of_ano": pedido_dict.get("of_ano", ""),
                    "obs_recebimento": pedido_dict.get("obs_recebimento", ""),
                    "entrega_em": pedido_dict.get("entrega_em", ""),
                    "entrega_cliente_codigo": pedido_dict.get("entrega_cliente_codigo", ""),
                    "pendente_desde": pedido_dict.get("pendente_desde", ""),
                    "data_producao": pedido_dict.get("data_producao", ""),
                    "parte": str(pedido_dict.get("parte", "")),
                    "divisao_automatica": str(pedido_dict.get("divisao_automatica", "") or ""),
                    "peso_total_linha": str(pedido_dict.get("peso_total_linha", "") or ""),
                    "cliente": pedido_dict.get("cliente", ""),
                    "cliente_codigo": pedido_dict.get("cliente_codigo", ""),
                    "representante": pedido_dict.get("representante", ""),
                    "bairro_destino": pedido_dict.get("bairro_destino", ""),
                    "cidade_destino": pedido_dict.get("cidade_destino", ""),
                    "rota_logistica": pedido_dict.get("rota_logistica", ""),
                    "peso_kg": str(pedido_dict.get("peso_kg", 0)),
                    "motivo": motivo or "RECEBIMENTO POSTERGADO",
                    "tipo_backlog": config.COD_BACKLOG_FUTURO,
                    "aceita_antecipacao": pedido_dict.get("aceita_antecipacao", "SIM"),
                    "is_spyder": pedido_dict.get("is_spyder", "NAO"),
                    "is_dimensao_longa": pedido_dict.get("is_dimensao_longa", "NAO"),
                }
            )
            self._calcular_oportunidades()
        elif destino_upper == config.COD_BACKLOG_LOCAL:
            self.backlog_local.append(
                {
                    "numero_pedido": pedido_dict.get("numero_pedido", ""),
                    "id_carga": _cid(pedido_dict),
                    "id_item": pedido_dict.get("id_item", ""),
                    "of_ano": pedido_dict.get("of_ano", ""),
                    "obs_recebimento": pedido_dict.get("obs_recebimento", ""),
                    "entrega_em": pedido_dict.get("entrega_em", ""),
                    "entrega_cliente_codigo": pedido_dict.get("entrega_cliente_codigo", ""),
                    "pendente_desde": pedido_dict.get("pendente_desde", ""),
                    "data_producao": pedido_dict.get("data_producao", ""),
                    "parte": str(pedido_dict.get("parte", "")),
                    "divisao_automatica": str(pedido_dict.get("divisao_automatica", "") or ""),
                    "peso_total_linha": str(pedido_dict.get("peso_total_linha", "") or ""),
                    "cliente": pedido_dict.get("cliente", ""),
                    "cliente_codigo": pedido_dict.get("cliente_codigo", ""),
                    "representante": pedido_dict.get("representante", ""),
                    "bairro_destino": pedido_dict.get("bairro_destino", ""),
                    "cidade_destino": pedido_dict.get("cidade_destino", ""),
                    "rota_logistica": pedido_dict.get("rota_logistica", ""),
                    "peso_kg": str(pedido_dict.get("peso_kg", 0)),
                    "motivo": motivo or "ENTREGA LOCAL",
                    "tipo_backlog": config.COD_BACKLOG_LOCAL,
                    "is_spyder": pedido_dict.get("is_spyder", "NAO"),
                    "is_dimensao_longa": pedido_dict.get("is_dimensao_longa", "NAO"),
                    "exige_syder": pedido_dict.get("exige_syder", "NAO"),
                    "enriquecido_mestre": pedido_dict.get("enriquecido_mestre", "NAO"),
                }
            )
        elif destino_upper == "COLETAS":
            self.coletas.append(
                {
                    "numero_pedido": pedido_dict.get("numero_pedido", ""),
                    "id_carga": _cid(pedido_dict),
                    "id_item": pedido_dict.get("id_item", ""),
                    "of_ano": pedido_dict.get("of_ano", ""),
                    "obs_recebimento": pedido_dict.get("obs_recebimento", ""),
                    "entrega_em": pedido_dict.get("entrega_em", ""),
                    "entrega_cliente_codigo": pedido_dict.get("entrega_cliente_codigo", ""),
                    "pendente_desde": pedido_dict.get("pendente_desde", ""),
                    "data_producao": pedido_dict.get("data_producao", ""),
                    "parte": str(pedido_dict.get("parte", "")),
                    "divisao_automatica": str(pedido_dict.get("divisao_automatica", "") or ""),
                    "peso_total_linha": str(pedido_dict.get("peso_total_linha", "") or ""),
                    "cliente": pedido_dict.get("cliente", ""),
                    "representante": pedido_dict.get("representante", ""),
                    "cidade_destino": pedido_dict.get("cidade_destino", ""),
                    "bairro_destino": pedido_dict.get("bairro_destino", ""),
                    "peso_kg": str(pedido_dict.get("peso_kg", 0)),
                    "motivo": motivo or "COLETA DE OPORTUNIDADE",
                }
            )
        else:
            retorno_vid = self._parse_retorno_destino(destino)
            if retorno_vid:
                ok, msg = self._validar_movimento_retorno(pedido_dict, retorno_vid)
                if not ok and not forcar:
                    self._restaurar_pedido(pedido_dict, origem)
                    return False, msg
                if not ok and forcar:
                    warning = msg
                item = self._dict_para_item(
                    pedido_dict,
                    len(self.itens_retorno_por_veiculo.get(retorno_vid, [])) + 1,
                )
                self.itens_retorno_por_veiculo.setdefault(retorno_vid, []).append(item)
            else:
                destino_ids = {r.veiculo_id for r in self.rotas}
                if destino not in destino_ids:
                    self._restaurar_pedido(pedido_dict, origem)
                    return False, f"Veículo destino inválido: {destino}"

                ok, msg = self._validar_movimento_veiculo(pedido_dict, destino)
                if not ok and not forcar:
                    self._restaurar_pedido(pedido_dict, origem)
                    return False, msg
                if not ok and forcar:
                    warning = msg

                item = self._dict_para_item(
                    pedido_dict, len(self.itens_por_veiculo.get(destino, [])) + 1
                )
                self.itens_por_veiculo.setdefault(destino, []).append(item)

        self._recalcular_apos_movimento(origem, destino, destino_upper, colunas_especiais)

        if origem == config.COD_BACKLOG_FUTURO or destino_upper == config.COD_BACKLOG_FUTURO:
            self._calcular_oportunidades()

        return True, warning

    def _restaurar_pedido(self, pedido_dict: dict[str, Any], origem: str | None) -> None:
        if not origem:
            return
        colunas_especiais = {
            "BACKLOG",
            "COLETAS",
            config.COD_BACKLOG_FUTURO,
            config.COD_BACKLOG_LOCAL,
        }
        if origem in colunas_especiais:
            return
        retorno_vid = self._parse_retorno_destino(origem)
        if retorno_vid:
            self.itens_retorno_por_veiculo.setdefault(retorno_vid, []).append(
                self._dict_para_item(pedido_dict, 1)
            )
            self.recalcular_metricas_retorno(retorno_vid)
        else:
            self.itens_por_veiculo.setdefault(origem, []).append(
                self._dict_para_item(pedido_dict, 1)
            )
            self.recalcular_metricas(origem)

    def _recalcular_apos_movimento(
        self,
        origem: str | None,
        destino: str,
        destino_upper: str,
        colunas_especiais: set[str],
    ) -> None:
        if origem:
            ret_orig = self._parse_retorno_destino(origem)
            if ret_orig:
                self.recalcular_metricas_retorno(ret_orig)
            elif origem not in colunas_especiais:
                self.recalcular_metricas(origem)

        ret_dest = self._parse_retorno_destino(destino)
        if ret_dest:
            self.recalcular_metricas_retorno(ret_dest)
        elif destino_upper not in colunas_especiais:
            self.recalcular_metricas(destino)

    def antecipar_para_hoje(self, numero_pedido: str) -> tuple[bool, str, str]:
        """Remove do backlog futuro e aloca em veículo compatível ou fila de hoje."""
        pedido_dict: dict[str, Any] | None = None
        for i, b in enumerate(self.backlog_futuro):
            if _mesma_carga(b, numero_pedido):
                pedido_dict = self._backlog_para_pedido(b)
                self.backlog_futuro.pop(i)
                break

        if not pedido_dict:
            return False, f"Pedido {numero_pedido} não está no backlog futuro.", ""

        melhor_vid = ""
        for rota in self.rotas:
            if rota.veiculo_id in self.veiculos_fechados:
                continue
            vocacao = rota.rota_vocacao
            if not vocacao:
                continue
            if not self._rotas_proximas(pedido_dict.get("rota_logistica", ""), vocacao):
                continue
            ok, _ = self._validar_movimento_veiculo(pedido_dict, rota.veiculo_id)
            if ok:
                melhor_vid = rota.veiculo_id
                break

        if not melhor_vid:
            for rota in self.rotas:
                if rota.veiculo_id in self.veiculos_fechados:
                    continue
                ok, _ = self._validar_movimento_veiculo(pedido_dict, rota.veiculo_id)
                if ok:
                    melhor_vid = rota.veiculo_id
                    break

        if melhor_vid:
            item = self._dict_para_item(
                pedido_dict, len(self.itens_por_veiculo.get(melhor_vid, [])) + 1
            )
            self.itens_por_veiculo.setdefault(melhor_vid, []).append(item)
            self.recalcular_metricas(melhor_vid)
            self._calcular_oportunidades()
            return True, "", melhor_vid

        self.backlog.append(
            {
                "numero_pedido": pedido_dict.get("numero_pedido", ""),
                "id_carga": _cid(pedido_dict),
                "id_item": pedido_dict.get("id_item", ""),
                "of_ano": pedido_dict.get("of_ano", ""),
                "obs_recebimento": pedido_dict.get("obs_recebimento", ""),
                "entrega_em": pedido_dict.get("entrega_em", ""),
                "entrega_cliente_codigo": pedido_dict.get("entrega_cliente_codigo", ""),
                "pendente_desde": pedido_dict.get("pendente_desde", ""),
                "data_producao": pedido_dict.get("data_producao", ""),
                "parte": str(pedido_dict.get("parte", "")),
                "divisao_automatica": str(pedido_dict.get("divisao_automatica", "") or ""),
                "peso_total_linha": str(pedido_dict.get("peso_total_linha", "") or ""),
                "cliente": pedido_dict.get("cliente", ""),
                "representante": pedido_dict.get("representante", ""),
                "cidade_destino": pedido_dict.get("cidade_destino", ""),
                "rota_logistica": pedido_dict.get("rota_logistica", ""),
                "peso_kg": str(pedido_dict.get("peso_kg", 0)),
                "motivo": "ANTECIPADO — aguardando alocação",
            }
        )
        self._calcular_oportunidades()
        return True, "", "BACKLOG"

    @staticmethod
    def _backlog_para_pedido(entry: dict[str, str]) -> dict[str, Any]:
        peso_raw = entry.get("peso_kg", "0")
        try:
            peso = float(peso_raw)
        except (TypeError, ValueError):
            peso = 0.0
        return {
            "numero_pedido": entry.get("numero_pedido", ""),
            "id_carga": _cid(entry),
            "id_item": entry.get("id_item", ""),
            "of_ano": entry.get("of_ano", ""),
            "obs_recebimento": entry.get("obs_recebimento", ""),
            "entrega_em": entry.get("entrega_em", ""),
            "entrega_cliente_codigo": entry.get("entrega_cliente_codigo", ""),
            "pendente_desde": entry.get("pendente_desde", ""),
            "data_producao": entry.get("data_producao", ""),
            "parte": str(entry.get("parte", "")),
            "divisao_automatica": str(entry.get("divisao_automatica", "") or ""),
            "peso_total_linha": str(entry.get("peso_total_linha", "") or ""),
            "cliente": entry.get("cliente", ""),
            "cliente_codigo": entry.get("cliente_codigo", ""),
            "representante": entry.get("representante", ""),
            "bairro_destino": entry.get("bairro_destino", ""),
            "cidade_destino": entry.get("cidade_destino", ""),
            "cep_destino": entry.get("cep_destino", ""),
            "rota_logistica": entry.get("rota_logistica", ""),
            "peso_kg": peso,
            "is_spyder": entry.get("is_spyder", "NAO"),
            "is_dimensao_longa": entry.get("is_dimensao_longa", "NAO"),
            "exige_syder": entry.get("exige_syder", "NAO"),
            "enriquecido_mestre": entry.get("enriquecido_mestre", "NAO"),
            "aceita_antecipacao": entry.get("aceita_antecipacao", "SIM"),
        }
