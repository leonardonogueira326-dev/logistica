"""
Motor de Logística — clusterização por rotas, alocação de frota e jornada.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import config
from models import ItemRota, PedidoConsolidado, RotaVeiculo
from normalizador import normalizar_texto, resolver_rota_logistica
from param_manager import carregar_parametros, rotulo_rota


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
        self.coletas: list[dict[str, str]] = []

    def carregar_pedidos(self, consolidados: list[PedidoConsolidado]) -> list[dict[str, Any]]:
        from datetime import date as date_cls

        hoje = date_cls.today().isoformat()
        pedidos: list[dict[str, Any]] = []
        for c in consolidados:
            if c.status not in (config.COD_LIBERADO, config.COD_TERCEIRO_HUB):
                continue

            data_prev = (c.data_prevista_recebimento or "").strip()
            if data_prev and data_prev > hoje:
                self.backlog_futuro.append(
                    {
                        "numero_pedido": c.numero_pedido,
                        "cliente": c.cliente,
                        "cliente_codigo": c.cliente_codigo,
                        "representante": c.representante,
                        "bairro_destino": c.bairro_destino or c.bairro,
                        "cidade_destino": c.cidade_destino or c.cidade,
                        "rota_logistica": c.rota_logistica,
                        "peso_kg": str(c.peso_kg),
                        "motivo": c.motivo_atraso or "RECEBIMENTO POSTERGADO",
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
            pedidos.append(
                {
                    "numero_pedido": c.numero_pedido,
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
        self.backlog = []
        self.backlog_futuro = []
        pedidos = self.carregar_pedidos(consolidados)
        clusters = self._agrupar_por_rota(pedidos)
        veiculos_ordem = self._ordem_veiculos(ativar_reserva)

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
            alocados_ids.add(ancora["numero_pedido"])
            estado.rota_vocacao = ancora["rota_logistica"]
            estado.regiao_predominante = rotulo_rota(estado.rota_vocacao)

            fila = self._fila_priorizada(estado, clusters, alocados_ids)
            for pedido in fila:
                ok, _ = self.pode_alocar(pedido, estado)
                if ok:
                    self._alocar_item(estado, pedido)
                    alocados_ids.add(pedido["numero_pedido"])

            if estado.itens:
                estados.append(estado)

        self.backlog = []
        for rota, lista in clusters.items():
            for p in lista:
                if p["numero_pedido"] not in alocados_ids:
                    self.backlog.append(
                        {
                            "numero_pedido": p["numero_pedido"],
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
        if not itens:
            return 0

        tempos_map = self.params.get("tempos_viagem_rota_min", {})
        tempo_viagem = max(
            tempos_map.get(i.get("rota_logistica", "ROTA_OUTROS"), tempos_map.get("ROTA_OUTROS", 300))
            for i in itens
        )

        paradas = self._contar_paradas_unicas(itens)
        descarga = int(self.params.get("tempo_descarga_minutos", 20))
        almoco = int(self.params.get("tempo_almoco_minutos", 60))

        return tempo_viagem + (paradas * descarga) + almoco

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
        for _rota, lista in clusters.items():
            for p in sorted(lista, key=lambda x: x["peso_kg"], reverse=True):
                if p["numero_pedido"] in alocados_ids:
                    continue
                ok, _ = self.pode_alocar(p, estado)
                if ok:
                    return p
        return None

    def _fila_priorizada(
        self,
        estado: EstadoVeiculo,
        clusters: dict[str, list[dict[str, Any]]],
        alocados_ids: set[str],
    ) -> list[dict[str, Any]]:
        vizinhas_raw = self.params.get("rotas_vizinhas", {}).get(estado.rota_vocacao, "")
        vizinhas = {v.strip() for v in vizinhas_raw.split(",") if v.strip()}
        rotas_ok = {estado.rota_vocacao} | vizinhas

        fila: list[dict[str, Any]] = []
        for rota in rotas_ok:
            for p in clusters.get(rota, []):
                if p["numero_pedido"] not in alocados_ids:
                    fila.append(p)
        return sorted(fila, key=lambda x: x["peso_kg"], reverse=True)

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

        return RotaVeiculo(
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

    @staticmethod
    def _dict_para_item(pedido: dict[str, Any], sequencia: int) -> ItemRota:
        return ItemRota(
            numero_pedido=pedido["numero_pedido"],
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
            if (item.get("aceita_antecipacao") or "SIM").upper() == "NAO":
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
        return {
            "rotas": [asdict(r) for r in self.rotas],
            "itens_por_veiculo": {
                vid: [asdict(i) for i in itens]
                for vid, itens in self.itens_por_veiculo.items()
            },
            "backlog": self.backlog,
            "backlog_futuro": self.backlog_futuro,
            "coletas": self.coletas,
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
            if dicts:
                self.recalcular_regiao(veiculo_id)
            else:
                rota.regiao_predominante = ""
                rota.rota_vocacao = ""
            break

        for seq, item in enumerate(itens, 1):
            item.sequencia_lifo = str(seq)

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
                if item.numero_pedido == numero_pedido:
                    pedido_dict = asdict(item)
                    origem = vid
                    self.itens_por_veiculo[vid].pop(i)
                    break
            if pedido_dict:
                break

        if not pedido_dict:
            for i, b in enumerate(self.backlog_futuro):
                if b.get("numero_pedido") == numero_pedido:
                    pedido_dict = self._backlog_para_pedido(b)
                    self.backlog_futuro.pop(i)
                    origem = config.COD_BACKLOG_FUTURO
                    break

        if not pedido_dict:
            for i, b in enumerate(self.backlog):
                if b.get("numero_pedido") == numero_pedido:
                    pedido_dict = self._backlog_para_pedido(b)
                    self.backlog.pop(i)
                    origem = "BACKLOG"
                    break

        if not pedido_dict:
            for i, c in enumerate(self.coletas):
                if c.get("numero_pedido") == numero_pedido:
                    pedido_dict = self._backlog_para_pedido(c)
                    self.coletas.pop(i)
                    origem = "COLETAS"
                    break

        if not pedido_dict:
            return False, f"Pedido {numero_pedido} não encontrado."

        warning = ""
        destino_upper = destino.upper()

        if destino_upper == "BACKLOG":
            self.backlog.append(
                {
                    "numero_pedido": pedido_dict.get("numero_pedido", ""),
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
        elif destino_upper == "COLETAS":
            self.coletas.append(
                {
                    "numero_pedido": pedido_dict.get("numero_pedido", ""),
                    "cliente": pedido_dict.get("cliente", ""),
                    "representante": pedido_dict.get("representante", ""),
                    "cidade_destino": pedido_dict.get("cidade_destino", ""),
                    "bairro_destino": pedido_dict.get("bairro_destino", ""),
                    "peso_kg": str(pedido_dict.get("peso_kg", 0)),
                    "motivo": motivo or "COLETA DE OPORTUNIDADE",
                }
            )
        else:
            destino_ids = {r.veiculo_id for r in self.rotas}
            if destino not in destino_ids:
                if origem and origem not in ("BACKLOG", "COLETAS", config.COD_BACKLOG_FUTURO):
                    self.itens_por_veiculo.setdefault(origem, []).append(
                        self._dict_para_item(pedido_dict, 1)
                    )
                return False, f"Veículo destino inválido: {destino}"

            ok, msg = self._validar_movimento_veiculo(pedido_dict, destino)
            if not ok and not forcar:
                if origem and origem not in ("BACKLOG", "COLETAS", config.COD_BACKLOG_FUTURO):
                    self.itens_por_veiculo.setdefault(origem, []).append(
                        self._dict_para_item(pedido_dict, 1)
                    )
                    self.recalcular_metricas(origem)
                return False, msg
            if not ok and forcar:
                warning = msg

            item = self._dict_para_item(
                pedido_dict, len(self.itens_por_veiculo.get(destino, [])) + 1
            )
            self.itens_por_veiculo.setdefault(destino, []).append(item)

        if origem and origem not in ("BACKLOG", "COLETAS", config.COD_BACKLOG_FUTURO):
            self.recalcular_metricas(origem)
        if destino_upper not in ("BACKLOG", "COLETAS", config.COD_BACKLOG_FUTURO):
            self.recalcular_metricas(destino)

        if origem == config.COD_BACKLOG_FUTURO or destino_upper == config.COD_BACKLOG_FUTURO:
            self._calcular_oportunidades()

        return True, warning

    def antecipar_para_hoje(self, numero_pedido: str) -> tuple[bool, str, str]:
        """Remove do backlog futuro e aloca em veículo compatível ou fila de hoje."""
        pedido_dict: dict[str, Any] | None = None
        for i, b in enumerate(self.backlog_futuro):
            if b.get("numero_pedido") == numero_pedido:
                pedido_dict = self._backlog_para_pedido(b)
                self.backlog_futuro.pop(i)
                break

        if not pedido_dict:
            return False, f"Pedido {numero_pedido} não está no backlog futuro.", ""

        melhor_vid = ""
        for rota in self.rotas:
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
