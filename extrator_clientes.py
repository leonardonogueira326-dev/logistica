"""
Cadastro mestre de clientes — lookup por Código (pandas).
Fonte: TESTE.xlsx - Planilha1.csv (preferencial) ou TESTE.xlsx.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

import config
from normalizador import normalizar_codigo_cliente, normalizar_texto


class CadastroClientes:
    """Hash map codigo_normalizado -> dados logísticos do cliente."""

    def __init__(self, pasta_ou_caminho: str = "") -> None:
        self._lookup: dict[str, dict[str, str]] = {}
        self._caminho_carregado: str = ""
        self._pasta_ou_caminho = pasta_ou_caminho

    def carregar(self, caminho: str = "") -> None:
        """Carrega CSV ou XLSX e constrói o lookup."""
        path = self._resolver_arquivo(caminho or self._pasta_ou_caminho)
        if not path:
            return

        df = self._ler_dataframe(path)
        if df is None or df.empty:
            return

        self._lookup = self._construir_lookup(df)
        self._caminho_carregado = str(path)

    def buscar_por_codigo(self, codigo: str) -> Optional[dict[str, str]]:
        chave = normalizar_codigo_cliente(codigo)
        if not chave:
            return None
        return self._lookup.get(chave)

    def total_clientes(self) -> int:
        return len(self._lookup)

    @property
    def caminho_carregado(self) -> str:
        return self._caminho_carregado

    @property
    def lookup(self) -> dict[str, dict[str, str]]:
        return self._lookup

    def _resolver_arquivo(self, pasta_ou_caminho: str) -> Optional[Path]:
        if not pasta_ou_caminho:
            return None

        caminho = Path(pasta_ou_caminho)
        if caminho.is_file():
            return caminho

        if caminho.is_dir():
            csv_path = caminho / config.ARQUIVO_CADASTRO_CSV
            if csv_path.exists():
                return csv_path
            xlsx_path = caminho / config.ARQUIVO_CADASTRO_XLSX
            if xlsx_path.exists():
                return xlsx_path
        return None

    def _ler_dataframe(self, path: Path) -> Optional[pd.DataFrame]:
        try:
            if path.suffix.lower() == ".csv":
                for encoding in ("utf-8", "latin1", "cp1252"):
                    for sep in (",", ";"):
                        try:
                            df = pd.read_csv(path, encoding=encoding, sep=sep, dtype=str)
                            if len(df.columns) >= 5:
                                return df
                        except Exception:
                            continue
                return pd.read_csv(path, encoding="latin1", sep=",", dtype=str)

            return pd.read_excel(path, sheet_name="Planilha1", dtype=str)
        except Exception:
            return None

    def _construir_lookup(self, df: pd.DataFrame) -> dict[str, dict[str, str]]:
        lookup: dict[str, dict[str, str]] = {}
        col_map = self._mapear_colunas(df.columns.tolist())

        for _, row in df.iterrows():
            try:
                codigo_raw = str(row.get(col_map["codigo"], "") or "").strip()
                chave = normalizar_codigo_cliente(codigo_raw)
                if not chave:
                    continue

                bairro = normalizar_texto(row.get(col_map["bairro"], ""))
                cidade = normalizar_texto(row.get(col_map["cidade"], ""))
                cep = str(row.get(col_map["cep"], "") or "").strip()
                representante = normalizar_texto(row.get(col_map["representante"], ""))
                razao = normalizar_texto(row.get(col_map["razao_social"], ""))
                endereco = normalizar_texto(row.get(col_map["endereco"], ""))
                rep_cod = str(row.get(col_map.get("representante_codigo", ""), "") or "").strip()

                lookup[chave] = {
                    "codigo": chave,
                    "razao_social": razao,
                    "endereco": endereco,
                    "bairro": bairro,
                    "cidade": cidade,
                    "cep": cep,
                    "representante_codigo": rep_cod,
                    "representante_nome": representante,
                    "representante": representante,
                }
            except Exception:
                continue

        return lookup

    @staticmethod
    def _mapear_colunas(colunas: list[str]) -> dict[str, str]:
        normalizadas = {c: c.strip().lower() for c in colunas}
        resultado: dict[str, str] = {}

        for col, norm in normalizadas.items():
            if norm in ("código", "codigo"):
                resultado["codigo"] = col
            elif "raz" in norm and "social" in norm:
                resultado["razao_social"] = col
            elif norm == "endereço" or norm == "endereco":
                resultado["endereco"] = col
            elif norm == "bairro":
                resultado["bairro"] = col
            elif norm == "cidade":
                resultado["cidade"] = col
            elif norm == "cep":
                resultado["cep"] = col
            elif "representante" in norm and "cód" not in norm and "cod" not in norm:
                resultado["representante"] = col
            elif "representante" in norm:
                resultado["representante_codigo"] = col

        return resultado


_cache_cadastro: dict[str, CadastroClientes] = {}
_cache_lookup: dict[str, dict[str, dict[str, str]]] = {}


def carregar_cadastro(pasta_dados: Path) -> dict[str, dict[str, str]]:
    """Carrega CSV/XLSX e retorna lookup dict codigo -> dados logísticos."""
    cadastro = CadastroClientes(str(pasta_dados))
    cadastro.carregar()
    return cadastro.lookup


def obter_lookup_clientes(pasta: str) -> dict[str, dict[str, str]]:
    """Retorna lookup cacheado (carrega uma vez por pasta)."""
    chave = str(Path(pasta).resolve()) if pasta else ""
    if chave not in _cache_lookup:
        _cache_lookup[chave] = carregar_cadastro(Path(pasta))
    return _cache_lookup[chave]


def obter_cadastro_clientes(pasta_ou_caminho: str) -> CadastroClientes:
    """Retorna instância cacheada do cadastro (recarrega se pasta mudar)."""
    chave = str(Path(pasta_ou_caminho).resolve()) if pasta_ou_caminho else ""
    if chave not in _cache_cadastro:
        cadastro = CadastroClientes(pasta_ou_caminho)
        cadastro.carregar()
        _cache_cadastro[chave] = cadastro
    return _cache_cadastro[chave]
