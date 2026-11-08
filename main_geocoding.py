#!/usr/bin/env python3
"""
Carga inicial de geocodificação — bases de clientes e transportadoras.

Lê:
  - base-de-clientes1.xlsx (aba Planilha1) — endereço completo, CEP, bairro
  - base-de-clientes.xlsx (fallback, aba Dados)
  - base-transportadoras.xlsx - Dados.csv (ou base-transportadoras.xlsx / aba Dados)

Gera:
  - data/cadastro_mestre_geolocalizado.json

Uso:
  python main_geocoding.py
  python main_geocoding.py --limite 5
  python main_geocoding.py --sem-rede
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from api.servico_geocoding import geocodificar_campos, montar_endereco_completo  # noqa: E402
from cadastro_geolocalizado import salvar_cadastro_geolocalizado  # noqa: E402
from normalizador import normalizar_texto  # noqa: E402

COL_ALIASES: dict[str, tuple[str, ...]] = {
    "codigo": ("codigo", "código", "cod"),
    "nome": ("razao_social", "razão social", "nome_fantasia", "nome"),
    "cnpj": ("cpf_cnpj", "cpf/cnpj", "cnpj", "cpf"),
    "rua": ("rua", "endereco", "endereço", "logradouro"),
    "numero": ("numero", "número", "num", "nro"),
    "bairro": ("bairro",),
    "cidade": ("cidade", "municipio", "município"),
    "estado": ("estado", "uf"),
    "cep": ("cep", "codigo_postal"),
}


def _normalizar_col(nome: str) -> str:
    return (
        normalizar_texto(nome)
        .replace(" ", "_")
        .replace("/", "_")
        .replace("-", "_")
    )


def _mapear_colunas(colunas: list[str]) -> dict[str, str]:
    norm_cols = {_normalizar_col(c): c for c in colunas}
    resultado: dict[str, str] = {}
    for destino, aliases in COL_ALIASES.items():
        for alias in aliases:
            chave = _normalizar_col(alias)
            if chave in norm_cols:
                resultado[destino] = norm_cols[chave]
                break
    return resultado


def _ler_base(
    caminho_csv: str,
    caminhos_xlsx: str | tuple[str, ...],
    sheets: tuple[str, ...] = ("Planilha1", "Dados"),
) -> pd.DataFrame:
    raiz = PROJECT_ROOT
    csv_path = raiz / caminho_csv
    if csv_path.is_file():
        for encoding in ("utf-8-sig", "utf-8", "latin1", "cp1252"):
            for sep in (";", ","):
                try:
                    df = pd.read_csv(csv_path, encoding=encoding, sep=sep, dtype=str)
                    if len(df.columns) >= 2:
                        return df.fillna("")
                except Exception:
                    continue
        return pd.read_csv(csv_path, encoding="latin1", sep=",", dtype=str).fillna("")

    nomes_xlsx = (caminhos_xlsx,) if isinstance(caminhos_xlsx, str) else caminhos_xlsx
    tentativas = list(dict.fromkeys(nomes_xlsx))

    for nome in tentativas:
        xlsx_path = raiz / nome
        if not xlsx_path.is_file():
            continue
        xl = pd.ExcelFile(xlsx_path)
        for sheet in sheets:
            if sheet in xl.sheet_names:
                print(f"  Lendo {xlsx_path.name} / aba «{sheet}»")
                return pd.read_excel(xlsx_path, sheet_name=sheet, dtype=str).fillna("")
        if xl.sheet_names:
            sheet = xl.sheet_names[0]
            print(f"  Lendo {xlsx_path.name} / aba «{sheet}» (única disponível)")
            return pd.read_excel(xlsx_path, sheet_name=sheet, dtype=str).fillna("")

    esperados = ", ".join(tentativas)
    raise FileNotFoundError(
        f"Base não encontrada. Esperado CSV ou um de [{esperados}] na raiz do projeto."
    )


def _valor(row: pd.Series, col_map: dict[str, str], campo: str) -> str:
    col = col_map.get(campo)
    if not col:
        return ""
    return str(row.get(col, "") or "").strip()


def _linha_para_registro(
    row: pd.Series,
    col_map: dict[str, str],
    tipo: str,
    *,
    usar_rede: bool,
) -> dict[str, Any]:
    codigo = _valor(row, col_map, "codigo")
    nome = _valor(row, col_map, "nome")
    cnpj = _valor(row, col_map, "cnpj")
    rua = _valor(row, col_map, "rua")
    numero = _valor(row, col_map, "numero")
    bairro = _valor(row, col_map, "bairro")
    cidade = _valor(row, col_map, "cidade")
    estado = _valor(row, col_map, "estado")
    cep = _valor(row, col_map, "cep")

    endereco_completo = montar_endereco_completo(rua, numero, bairro, cidade, estado, cep)
    if not endereco_completo and nome and cidade:
        endereco_completo = montar_endereco_completo("", "", "", cidade, estado, cep)
    if not endereco_completo and nome:
        endereco_completo = nome

    coords = geocodificar_campos(
        rua=rua,
        numero=numero,
        bairro=bairro,
        cidade=cidade,
        estado=estado,
        cep=cep,
        usar_rede=usar_rede,
    )

    registro_id = cnpj or codigo or nome
    return {
        "id": registro_id,
        "codigo": codigo,
        "cnpj": cnpj,
        "nome": nome,
        "tipo": tipo,
        "endereco_completo": endereco_completo,
        "rua": rua,
        "numero": numero,
        "bairro": bairro,
        "cidade": normalizar_texto(cidade),
        "estado": normalizar_texto(estado),
        "cep": cep,
        "latitude": coords["latitude"],
        "longitude": coords["longitude"],
    }


def processar_base(
    df: pd.DataFrame,
    tipo: str,
    *,
    limite: int | None,
    usar_rede: bool,
    offset_contador: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    col_map = _mapear_colunas(list(df.columns))
    stats = {"total": 0, "geocodificados": 0, "falhas": 0, "sem_endereco": 0}
    registros: list[dict[str, Any]] = []
    processados_rede = 0

    for _, row in df.iterrows():
        if limite is not None and (offset_contador + stats["total"]) >= limite:
            break

        codigo = _valor(row, col_map, "codigo")
        nome = _valor(row, col_map, "nome")
        if not codigo and not nome:
            continue

        stats["total"] += 1
        registro = _linha_para_registro(row, col_map, tipo, usar_rede=usar_rede)
        registros.append(registro)

        if not registro["cidade"] and not registro["cep"] and not registro["rua"]:
            stats["sem_endereco"] += 1

        if registro["latitude"] is not None and registro["longitude"] is not None:
            stats["geocodificados"] += 1
        elif usar_rede and (registro["cidade"] or registro["cep"] or registro["rua"]):
            stats["falhas"] += 1
            processados_rede += 1

        if stats["total"] % 25 == 0:
            print(f"  … {stats['total']} registros processados ({tipo})")

    return registros, stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Geocodifica bases de clientes e transportadoras via Nominatim.",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Máximo total de linhas a processar (útil para testes).",
    )
    parser.add_argument(
        "--sem-rede",
        action="store_true",
        help="Não chama Nominatim; grava latitude/longitude null (dry-run estrutural).",
    )
    parser.add_argument(
        "--clientes",
        default="",
        help="Arquivo XLSX/CSV de clientes (padrão: base-de-clientes1.xlsx).",
    )
    args = parser.parse_args()

    usar_rede = not args.sem_rede
    print("Superfine Logística — Geocodificação Fase A")
    print(f"User-Agent: {config.NOMINATIM_USER_AGENT}")
    print(f"Intervalo: {config.NOMINATIM_INTERVALO_SEG}s entre requisições")
    print(f"Rede Nominatim: {'SIM' if usar_rede else 'NÃO (dry-run)'}\n")

    try:
        clientes_xlsx = args.clientes.strip() or config.ARQUIVO_BASE_CLIENTES_XLSX_FALLBACKS
        df_clientes = _ler_base(
            config.ARQUIVO_BASE_CLIENTES_CSV,
            clientes_xlsx,
            sheets=config.ARQUIVO_BASE_CLIENTES_SHEETS,
        )
        df_transp = _ler_base(
            config.ARQUIVO_BASE_TRANSPORTADORAS_CSV,
            config.ARQUIVO_BASE_TRANSPORTADORAS_XLSX,
            sheets=("Dados", "Planilha1"),
        )
    except FileNotFoundError as exc:
        print(f"Erro: {exc}")
        return 1

    print(f"Clientes: {len(df_clientes)} linhas | Transportadoras: {len(df_transp)} linhas\n")

    todos: list[dict[str, Any]] = []
    stats_total = {"total": 0, "geocodificados": 0, "falhas": 0, "sem_endereco": 0}

    print("Processando clientes…")
    regs_cli, st_cli = processar_base(
        df_clientes, "Cliente", limite=args.limite, usar_rede=usar_rede, offset_contador=0
    )
    todos.extend(regs_cli)
    for k in stats_total:
        stats_total[k] += st_cli[k]

    restante = None
    if args.limite is not None:
        restante = max(0, args.limite - stats_total["total"])

    if restante is None or restante > 0:
        print("Processando transportadoras…")
        regs_tr, st_tr = processar_base(
            df_transp,
            "Transportadora",
            limite=restante if restante is not None else None,
            usar_rede=usar_rede,
            offset_contador=stats_total["total"],
        )
        todos.extend(regs_tr)
        for k in stats_total:
            stats_total[k] += st_tr[k]

    destino = salvar_cadastro_geolocalizado(todos)
    print(f"\nArquivo gerado: {destino}")
    print("Resumo:")
    print(f"  Total registros  : {stats_total['total']}")
    print(f"  Geocodificados   : {stats_total['geocodificados']}")
    print(f"  Sem endereço     : {stats_total['sem_endereco']}")
    print(f"  Falhas Nominatim : {stats_total['falhas']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
