"""
Cadastro mestre de clientes — lookup por Código (pandas).
Fonte: TESTE.xlsx - Planilha1.csv (preferencial) ou TESTE.xlsx.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd

import config
from normalizador import normalizar_codigo_cliente, normalizar_texto


class CadastroClientes:
    """Hash map codigo_normalizado -> dados logísticos do cliente."""

    def __init__(self, pasta_ou_caminho: str = "") -> None:
        self._lookup: dict[str, dict[str, str]] = {}
        self._caminho_carregado: str = ""
        self._pasta_ou_caminho = pasta_ou_caminho
        self._df: pd.DataFrame | None = None
        self._col_map: dict[str, str] = {}
        self._sheet_name = "Planilha1"

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
        self._df = df.copy()
        self._col_map = self._mapear_colunas(df.columns.tolist())
        self._garantir_colunas_coordenadas()

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

    def _garantir_colunas_coordenadas(self) -> None:
        if self._df is None:
            return
        if "latitude" not in self._col_map:
            self._df["Latitude"] = ""
            self._col_map["latitude"] = "Latitude"
        if "longitude" not in self._col_map:
            self._df["Longitude"] = ""
            self._col_map["longitude"] = "Longitude"

    def _indice_por_codigo(self, codigo: str) -> int | None:
        if self._df is None or "codigo" not in self._col_map:
            return None
        col = self._col_map["codigo"]
        for idx, val in self._df[col].items():
            if normalizar_codigo_cliente(str(val or "")) == codigo:
                return int(idx)
        return None

    def atualizar_coordenadas(self, codigo: str, latitude: float, longitude: float) -> bool:
        chave = normalizar_codigo_cliente(codigo)
        if not chave or chave not in self._lookup:
            return False

        lat_str = f"{latitude:.6f}"
        lon_str = f"{longitude:.6f}"
        self._lookup[chave]["latitude"] = lat_str
        self._lookup[chave]["longitude"] = lon_str

        if self._df is not None:
            idx = self._indice_por_codigo(chave)
            if idx is not None:
                self._df.at[idx, self._col_map["latitude"]] = lat_str
                self._df.at[idx, self._col_map["longitude"]] = lon_str
        return True

    def inserir_cliente(self, dados: dict[str, Any], latitude: float, longitude: float) -> bool:
        codigo = normalizar_codigo_cliente(str(dados.get("codigo") or ""))
        if not codigo or self._df is None:
            return False

        self._garantir_colunas_coordenadas()
        nova_linha: dict[str, Any] = {}
        for chave, col in self._col_map.items():
            nova_linha[col] = ""

        if "codigo" in self._col_map:
            nova_linha[self._col_map["codigo"]] = codigo
        if "razao_social" in self._col_map:
            nova_linha[self._col_map["razao_social"]] = dados.get("razao_social", "")
        if "endereco" in self._col_map:
            nova_linha[self._col_map["endereco"]] = dados.get("endereco", "")
        if "bairro" in self._col_map:
            nova_linha[self._col_map["bairro"]] = dados.get("bairro", "")
        if "cidade" in self._col_map:
            nova_linha[self._col_map["cidade"]] = dados.get("cidade", "")
        if "estado" in self._col_map:
            nova_linha[self._col_map["estado"]] = dados.get("estado", "")
        if "cep" in self._col_map:
            nova_linha[self._col_map["cep"]] = dados.get("cep", "")
        if "representante" in self._col_map:
            nova_linha[self._col_map["representante"]] = dados.get("representante", "")

        nova_linha[self._col_map["latitude"]] = f"{latitude:.6f}"
        nova_linha[self._col_map["longitude"]] = f"{longitude:.6f}"

        self._df = pd.concat([self._df, pd.DataFrame([nova_linha])], ignore_index=True)
        self._lookup = self._construir_lookup(self._df)
        return True

    def salvar(self, caminho: str = "") -> str:
        destino = Path(caminho or self._caminho_carregado)
        if not destino or self._df is None:
            raise ValueError("Nenhum cadastro carregado para salvar.")

        if destino.suffix.lower() == ".csv":
            self._df.to_csv(destino, index=False, encoding="utf-8-sig")
        else:
            self._df.to_excel(destino, sheet_name=self._sheet_name, index=False)

        self._caminho_carregado = str(destino)
        return str(destino)

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
                aceita_raw = str(row.get(col_map.get("aceita_antecipacao", ""), "") or "").strip().upper()
                if aceita_raw in ("NAO", "NÃO", "N", "0", "FALSE", "NAO ACEITA", "NÃO ACEITA"):
                    aceita = "NAO"
                elif aceita_raw:
                    aceita = "SIM"
                else:
                    aceita = "SIM"

                estado_col = col_map.get("estado")
                lat_col = col_map.get("latitude")
                lon_col = col_map.get("longitude")

                lookup[chave] = {
                    "codigo": chave,
                    "razao_social": razao,
                    "endereco": endereco,
                    "bairro": bairro,
                    "cidade": cidade,
                    "estado": normalizar_texto(row.get(estado_col, "")) if estado_col else "",
                    "cep": cep,
                    "representante_codigo": rep_cod,
                    "representante_nome": representante,
                    "representante": representante,
                    "aceita_antecipacao": aceita,
                    "latitude": str(row.get(lat_col, "") or "").strip() if lat_col else "",
                    "longitude": str(row.get(lon_col, "") or "").strip() if lon_col else "",
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
            elif "aceita" in norm and "antecip" in norm:
                resultado["aceita_antecipacao"] = col
            elif norm in ("latitude", "lat"):
                resultado["latitude"] = col
            elif norm in ("longitude", "long", "lng", "lon"):
                resultado["longitude"] = col
            elif norm in ("estado", "uf"):
                resultado["estado"] = col

        return resultado


def resolver_arquivo_cadastro(pasta_dados: str = "") -> Path | None:
    """Resolve caminho do cadastro mestre (config operacional → pasta de dados)."""
    try:
        from param_manager import carregar_parametros

        params = carregar_parametros()
    except Exception:
        params = {}

    rel = str(params.get("cadastro_clientes_path", config.ARQUIVO_CADASTRO_XLSX)).strip()
    raiz = Path(__file__).resolve().parent

    candidatos: list[Path] = []
    if rel:
        p = Path(rel)
        candidatos.append(p if p.is_absolute() else raiz / p)

    if pasta_dados:
        cadastro = CadastroClientes(pasta_dados)
        resolvido = cadastro._resolver_arquivo(pasta_dados)
        if resolvido:
            candidatos.append(resolvido)

    candidatos.extend([raiz / config.ARQUIVO_CADASTRO_XLSX, raiz / config.ARQUIVO_CADASTRO_CSV])

    vistos: set[str] = set()
    for cand in candidatos:
        if not cand:
            continue
        chave = str(cand.resolve())
        if chave in vistos:
            continue
        vistos.add(chave)
        if cand.is_file():
            return cand
    return None


def invalidar_cache_cadastro() -> None:
    _cache_cadastro.clear()
    _cache_lookup.clear()


_cache_cadastro: dict[str, CadastroClientes] = {}
_cache_lookup: dict[str, dict[str, dict[str, str]]] = {}


def carregar_cadastro(pasta_dados: Path) -> dict[str, dict[str, str]]:
    """Carrega CSV/XLSX e retorna lookup dict codigo -> dados logísticos."""
    path = resolver_arquivo_cadastro(str(pasta_dados))
    cadastro = CadastroClientes(str(path) if path else str(pasta_dados))
    cadastro.carregar(str(path) if path else "")
    return cadastro.lookup


def _lookup_planilha_dados(path: Path) -> dict[str, dict[str, str]]:
    """
    base-de-clientes.xlsx (aba Dados, exportada pelo sistema da empresa):
    CODIGO, RAZAO_SOCIAL, NOME_FANTASIA, ENDERECO, NUMERO, BAIRRO, COMPLEMENTO,
    CIDADE, UF, CEP, TELEFONE, EMAIL, CODIGO_REPRESENTANTE, REPRESENTANTE_*, STATUS.
    É a mais atualizada (clientes novos). Exportações antigas não traziam o
    endereço: aí esses campos ficam vazios e a base1 completa.
    """
    try:
        df = pd.read_excel(path, sheet_name="Dados", dtype=str)
    except Exception:
        return {}
    cols = {c.strip().upper(): c for c in df.columns}
    if "CODIGO" not in cols or "CIDADE" not in cols:
        return {}
    pega = lambda row, nome: str(row.get(cols.get(nome, ""), "") or "").strip()  # noqa: E731
    lookup: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        chave = normalizar_codigo_cliente(pega(row, "CODIGO"))
        if not chave:
            continue
        rep = normalizar_texto(pega(row, "REPRESENTANTE_FANTASIA") or pega(row, "REPRESENTANTE_RAZAO"))
        rua, numero = normalizar_texto(pega(row, "ENDERECO")), pega(row, "NUMERO")
        if rua and numero and numero.upper() not in ("0", "S/N", "SN"):
            rua = f"{rua}, {normalizar_texto(numero)}"
        lookup[chave] = {
            "codigo": chave,
            "razao_social": normalizar_texto(pega(row, "RAZAO_SOCIAL")),
            "nome_fantasia": normalizar_texto(pega(row, "NOME_FANTASIA")),
            "endereco": rua,
            "bairro": normalizar_texto(pega(row, "BAIRRO")),
            "cidade": normalizar_texto(pega(row, "CIDADE")),
            "estado": normalizar_texto(pega(row, "UF")),
            "cep": pega(row, "CEP"),
            "telefone": pega(row, "TELEFONE"),
            "status_cliente": normalizar_texto(pega(row, "STATUS")),
            "representante_codigo": pega(row, "CODIGO_REPRESENTANTE"),
            "representante_nome": rep,
            "representante": rep,
            "aceita_antecipacao": "SIM",
            "latitude": "",
            "longitude": "",
        }
    return lookup


def _bases_da_raiz() -> list[Path]:
    raiz = Path(__file__).resolve().parent
    return [raiz / n for n in config.ARQUIVO_BASE_CLIENTES_XLSX_FALLBACKS if (raiz / n).exists()]


def obter_lookup_clientes(pasta: str) -> dict[str, dict[str, str]]:
    """
    Lookup código -> dados do cliente, juntando tudo que existir:
    1) cadastro configurado (se o arquivo existir);
    2) base-de-clientes1.xlsx (Planilha1: endereço, bairro, CEP);
    3) base-de-clientes.xlsx (Dados: a mais atualizada, só cidade/UF/representante).
    Um campo vazio numa fonte é completado pela seguinte.
    """
    path = resolver_arquivo_cadastro(pasta)
    bases = _bases_da_raiz()
    chave = "|".join(
        f"{p.resolve()}:{p.stat().st_mtime_ns}" for p in ([path] if path else []) + bases
    ) or (str(Path(pasta).resolve()) if pasta else "")
    if chave in _cache_lookup:
        return _cache_lookup[chave]

    fontes: list[dict[str, dict[str, str]]] = []
    if path:
        fontes.append(carregar_cadastro(Path(pasta) if pasta else Path(".")))
    for base in bases:
        cad = CadastroClientes(str(base))
        cad.carregar(str(base))
        fontes.append(cad.lookup or _lookup_planilha_dados(base))

    lookup: dict[str, dict[str, str]] = {}
    for fonte in fontes:
        for codigo, dados in fonte.items():
            atual = lookup.setdefault(codigo, dict(dados))
            for campo, valor in dados.items():
                if valor and not atual.get(campo):
                    atual[campo] = valor
    _cache_lookup[chave] = lookup
    return lookup


def obter_cadastro_clientes(pasta_ou_caminho: str) -> CadastroClientes:
    """Retorna instância cacheada do cadastro (recarrega se pasta mudar)."""
    path = resolver_arquivo_cadastro(pasta_ou_caminho)
    chave = str(path.resolve()) if path else str(Path(pasta_ou_caminho).resolve()) if pasta_ou_caminho else ""
    if chave not in _cache_cadastro:
        cadastro = CadastroClientes(str(path) if path else pasta_ou_caminho)
        cadastro.carregar(str(path) if path else "")
        _cache_cadastro[chave] = cadastro
    return _cache_cadastro[chave]
