"""
Motor de Logística — clusterização por rotas, alocação de frota e jornada.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import config
from models import ItemRota, PedidoConsolidado, RotaVeiculo
from normalizador import normalizar_texto, resolver_rota_logistica
from param_manager import carregar_parametros, rotulo_rota


def _cid(obj: Any) -> str:
    """Identidade da carga (pedido/item + OF [+ parte]); cai no nº do pedido em dados antigos."""
    if isinstance(obj, dict):
        return str(obj.get("id_carga") or obj.get("id_item") or obj.get("numero_pedido") or "")
    return str(
        getattr(obj, "id_carga", "") or getattr(obj, "id_item", "") or getattr(obj, "numero_pedido", "")
    )


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

    def verificar_efeito_elastico(self, veiculo_pedidos: list[dict[str, Any]]) -> dict[str, Any]:
        """Detecta mistura de corredores rodoviários na fila principal do veículo."""
        corredores: set[int] = set()
        for pedido in veiculo_pedidos:
            corredor = self._corredor_pedido(pedido)
            if corredor is not None:
                corredores.add(corredor)

        if len(corredores) <= 1:
            return {"alerta_elastico": False, "mensagem_alerta_elastico": ""}

        nums = sorted(corredores)
        if len(nums) == 2:
            rotulo = f"{nums[0]} e {nums[1]}"
        else:
            rotulo = ", ".join(str(n) for n in nums[:-1]) + f" e {nums[-1]}"
        return {
            "alerta_elastico": True,
            "mensagem_alerta_elastico": f"Conflito Geográfico: Mistura de Corredores [{rotulo}]",
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
        """TEO = Σ(tempo viagem cidades) + (qtd pedidos × 30 min) + 60 min almoço."""
        if not itens:
            return 0

        cidades: set[str] = set()
        for item in itens:
            cidade = normalizar_texto(item.get("cidade_destino", "")).replace("'", " ")
            if cidade:
                cidades.add(cidade)

        tempo_viagem = sum(self._tempo_viagem_cidade(c) for c in cidades)
        descarga = int(self.params.get("teo_tempo_descarga_minutos", config.TEO_TEMPO_DESCARGA_MIN))
        almoco = int(self.params.get("tempo_almoco_minutos", 60))
        return tempo_viagem + (len(itens) * descarga) + almoco

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
            if data_prev and data_prev > hoje:
                self.backlog_futuro.append(
                    {
                        "numero_pedido": c.numero_pedido,
                        "id_carga": c.id_item or c.numero_pedido,
                        "id_item": c.id_item or c.numero_pedido,
                        "of_ano": c.of_ano,
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

            if self._eh_cidade_local(cidade):
                self.backlog_local.append(
                    {
                        "numero_pedido": c.numero_pedido,
                        "id_carga": c.id_item or c.numero_pedido,
                        "id_item": c.id_item or c.numero_pedido,
                        "of_ano": c.of_ano,
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
                "id_carga": _cid(pedido_dict),
                "id_item": pedido_dict.get("id_item", ""),
                "of_ano": pedido_dict.get("of_ano", ""),
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
