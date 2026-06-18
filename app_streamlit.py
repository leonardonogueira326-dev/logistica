"""
Painel Streamlit — Superfine Logística Fase 2.

Uso:
    streamlit run app_streamlit.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import streamlit as st

import config
from motor_ingestao import MotorIngestao
from motor_logistica import MotorLogistica
from param_manager import carregar_parametros, rotulo_rota, salvar_parametros
from extrator_clientes import obter_cadastro_clientes

PASTA_PADRAO = r"c:\Users\Usuario\Desktop\logistica"


def _init_session() -> None:
    if "pasta_dados" not in st.session_state:
        st.session_state.pasta_dados = PASTA_PADRAO
    if "dados_ingestao" not in st.session_state:
        st.session_state.dados_ingestao = None
    if "motor_log" not in st.session_state:
        st.session_state.motor_log = None
    if "params" not in st.session_state:
        st.session_state.params = carregar_parametros()
    if "itens_veiculos" not in st.session_state:
        st.session_state.itens_veiculos = {}


def _carregar_json_ingestao(pasta: str) -> dict | None:
    path = Path(pasta) / f"ingestao_{date.today().isoformat()}.json"
    if not path.exists():
        candidatos = sorted(Path(pasta).glob("ingestao_*.json"), reverse=True)
        if candidatos:
            path = candidatos[0]
        else:
            return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _executar_ingestao(pasta: str) -> dict:
    motor = MotorIngestao(pasta)
    motor.executar()
    dados = motor.para_dict()
    json_path = Path(pasta) / f"ingestao_{date.today().isoformat()}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    return dados


def _executar_roteirizacao(dados: dict, params: dict, ativar_reserva: bool) -> MotorLogistica:
    from models import PedidoConsolidado

    consolidados = [PedidoConsolidado(**c) for c in dados.get("consolidados", [])]
    motor = MotorLogistica(params)
    motor.alocar_frota(consolidados, ativar_reserva=ativar_reserva)
    return motor


def _badge_mestre(enriquecido: str) -> str:
    return "Mestre" if enriquecido == "SIM" else "PDF"


def aba_montagem(motor_log: MotorLogistica) -> None:
    st.subheader("Montagem de Cargas")
    if not motor_log or not motor_log.rotas:
        st.info("Nenhuma rota alocada. Execute a ingestão e roteirização.")
        return

    for rota in motor_log.rotas:
        with st.expander(
            f"{rota.veiculo_nome} | Rota: {rota.regiao_predominante} | "
            f"{rota.peso_alocado_kg:.0f} kg / {rota.capacidade_kg:.0f} kg ({rota.eficiencia_pct})",
            expanded=True,
        ):
            st.caption(
                f"Jornada: {int(rota.tempo_total_min) // 60}h {int(rota.tempo_total_min) % 60}min "
                f"/ {int(st.session_state.params.get('jornada_maxima_minutos', 600)) // 60}h | "
                f"Paradas: {rota.qtd_paradas} | Retorno: {rota.retorno_previsto}"
            )
            itens = motor_log.itens_por_veiculo.get(rota.veiculo_id, [])
            if itens:
                linhas = []
                for item in itens:
                    linhas.append(
                        {
                            "Pedido": item.numero_pedido,
                            "Cliente": item.cliente[:40],
                            "Bairro": item.bairro_destino,
                            "Cidade": item.cidade_destino,
                            "CEP": item.cep_destino,
                            "Rota": rotulo_rota(item.rota_logistica),
                            "Peso": f"{item.peso_kg:.0f} kg",
                            "Fonte": _badge_mestre(item.enriquecido_mestre),
                        }
                    )
                st.dataframe(linhas, use_container_width=True, hide_index=True)


def aba_backlog(motor_log: MotorLogistica | None, dados: dict | None) -> None:
    st.subheader("Fila de Espera / Backlog")

    representantes = set()
    backlog: list[dict] = []

    if motor_log and motor_log.backlog:
        backlog.extend(motor_log.backlog)

    if dados:
        for c in dados.get("consolidados", []):
            if c.get("status") != config.COD_LIBERADO:
                backlog.append(
                    {
                        "numero_pedido": c.get("numero_pedido", ""),
                        "cliente": c.get("cliente", ""),
                        "representante": c.get("representante", "NÃO IDENTIFICADO"),
                        "cidade_destino": c.get("cidade_destino", c.get("cidade", "")),
                        "rota_logistica": c.get("rota_logistica", ""),
                        "peso_kg": str(c.get("peso_kg", 0)),
                        "motivo": c.get("status", "") + " — " + c.get("motivo_bloqueio", ""),
                    }
                )
            rep = c.get("representante", "")
            if rep:
                representantes.add(rep)

    filtro_rep = st.selectbox(
        "Filtrar por Representante",
        ["TODOS"] + sorted(representantes),
    )

    if filtro_rep != "TODOS":
        backlog = [b for b in backlog if b.get("representante") == filtro_rep]

    if backlog:
        st.dataframe(
            [
                {
                    "Pedido": b.get("numero_pedido"),
                    "Cliente": b.get("cliente", "")[:40],
                    "Representante": b.get("representante"),
                    "Cidade": b.get("cidade_destino"),
                    "Rota": rotulo_rota(b.get("rota_logistica", "")),
                    "Peso": b.get("peso_kg"),
                    "Motivo": b.get("motivo"),
                }
                for b in backlog
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("Nenhum pedido no backlog.")


def aba_coletas(dados: dict | None) -> None:
    st.subheader("Coletas Disponíveis")
    if not dados:
        st.info("Execute a ingestão primeiro.")
        return

    eventos = dados.get("eventos_email", [])
    coletas = [e for e in eventos if e.get("tipo_evento") != config.COD_TRAVADO_COMERCIAL]

    if coletas:
        st.dataframe(
            [
                {
                    "Data": e.get("data"),
                    "Cliente": e.get("cliente"),
                    "NF": e.get("nf"),
                    "Bairro": e.get("bairro"),
                    "Cidade": e.get("cidade"),
                    "Obs": e.get("observacao", "")[:60],
                }
                for e in coletas
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Nenhuma coleta identificada no e-mail do dia.")


def aba_parametros() -> None:
    st.subheader("Parâmetros Logísticos")
    params = st.session_state.params

    st.text_input(
        "Caminho cadastro clientes (relativo à pasta de dados)",
        value=params.get("cadastro_clientes_path", config.ARQUIVO_CADASTRO_XLSX),
        key="cadastro_path_input",
    )

    if st.button("Carregar Cadastro de Clientes"):
        pasta = st.session_state.pasta_dados
        cad = obter_cadastro_clientes(pasta)
        st.success(f"{cad.total_clientes()} clientes carregados de {cad.caminho_carregado or 'N/A'}")

    st.markdown("**De-Para Cidades → Rotas**")
    mapeamento = params.get("mapeamento_cidades_rotas", {})
    df_map = [{"Cidade": k, "Rota": v} for k, v in sorted(mapeamento.items())]
    edited_map = st.data_editor(df_map, num_rows="dynamic", use_container_width=True, key="editor_map")

    st.markdown("**Tempos de viagem por rota (minutos)**")
    tempos = params.get("tempos_viagem_rota_min", {})
    df_tempos = [{"Rota": k, "Minutos": v} for k, v in sorted(tempos.items())]
    edited_tempos = st.data_editor(df_tempos, num_rows="dynamic", use_container_width=True, key="editor_tempos")

    col1, col2, col3 = st.columns(3)
    with col1:
        params["tempo_descarga_minutos"] = st.number_input(
            "Descarga (min)", value=int(params.get("tempo_descarga_minutos", 20))
        )
    with col2:
        params["tempo_almoco_minutos"] = st.number_input(
            "Almoço (min)", value=int(params.get("tempo_almoco_minutos", 60))
        )
    with col3:
        params["jornada_maxima_minutos"] = st.number_input(
            "Jornada máx (min)", value=int(params.get("jornada_maxima_minutos", 600))
        )

    if st.button("Salvar Parâmetros"):
        params["mapeamento_cidades_rotas"] = {
            row["Cidade"].upper(): row["Rota"] for row in edited_map if row.get("Cidade")
        }
        params["tempos_viagem_rota_min"] = {
            row["Rota"]: int(row["Minutos"]) for row in edited_tempos if row.get("Rota")
        }
        params["cadastro_clientes_path"] = st.session_state.get(
            "cadastro_path_input", config.ARQUIVO_CADASTRO_XLSX
        )
        salvar_parametros(params)
        st.session_state.params = params
        st.success("Parâmetros salvos.")


def aba_retencoes_log(dados: dict | None) -> None:
    st.subheader("Retenções / Log de Ingestão")
    if not dados:
        st.info("Execute a ingestão primeiro.")
        return

    resumo = dados.get("resumo", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pedidos PDF", resumo.get("pedidos_pdf", "0"))
    c2.metric("Liberados", resumo.get("liberados", "0"))
    c3.metric("Enriquecidos Mestre", resumo.get("enriquecidos_mestre", "0/0"))
    c4.metric("Cadastro Clientes", resumo.get("cadastro_clientes", "0"))

    st.markdown("**Retenções XLSB**")
    ret = dados.get("retencoes_xlsb", [])
    if ret:
        st.dataframe(ret[:50], use_container_width=True, hide_index=True)
    else:
        st.info("Sem retenções.")

    st.markdown("**Avisos**")
    avisos = resumo.get("avisos", "NENHUM")
    if avisos != "NENHUM":
        for aviso in avisos.split(" | "):
            if "não cadastrado" in aviso.lower() or "warning" in aviso.lower():
                st.warning(aviso)
            else:
                st.info(aviso)
    else:
        st.success("Nenhum aviso.")


def main() -> None:
    st.set_page_config(page_title="Superfine Logística", layout="wide")
    st.title("Superfine — Painel Logístico (Fase 2)")
    _init_session()

    with st.sidebar:
        st.header("Controles")
        st.session_state.pasta_dados = st.text_input(
            "Pasta de dados", value=st.session_state.pasta_dados
        )
        ativar_reserva = st.checkbox("Ativar Van Master (reserva)", value=False)

        if st.button("Executar Ingestão", type="primary"):
            with st.spinner("Processando PDF, XLSB e MSG..."):
                st.session_state.dados_ingestao = _executar_ingestao(
                    st.session_state.pasta_dados
                )
            st.success("Ingestão concluída.")

        if st.button("Executar Roteirização"):
            if not st.session_state.dados_ingestao:
                st.session_state.dados_ingestao = _carregar_json_ingestao(
                    st.session_state.pasta_dados
                )
            if st.session_state.dados_ingestao:
                st.session_state.motor_log = _executar_roteirizacao(
                    st.session_state.dados_ingestao,
                    st.session_state.params,
                    ativar_reserva,
                )
                st.success("Roteirização concluída.")
            else:
                st.error("JSON de ingestão não encontrado.")

        if st.session_state.dados_ingestao is None:
            st.session_state.dados_ingestao = _carregar_json_ingestao(
                st.session_state.pasta_dados
            )
            if st.session_state.dados_ingestao and st.session_state.motor_log is None:
                st.session_state.motor_log = _executar_roteirizacao(
                    st.session_state.dados_ingestao,
                    st.session_state.params,
                    ativar_reserva,
                )

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "Montagem de Cargas",
            "Fila de Espera",
            "Coletas Disponíveis",
            "Parâmetros Logísticos",
            "Retenções / Log",
        ]
    )

    with tab1:
        aba_montagem(st.session_state.motor_log)
    with tab2:
        aba_backlog(st.session_state.motor_log, st.session_state.dados_ingestao)
    with tab3:
        aba_coletas(st.session_state.dados_ingestao)
    with tab4:
        aba_parametros()
    with tab5:
        aba_retencoes_log(st.session_state.dados_ingestao)


if __name__ == "__main__":
    main()
