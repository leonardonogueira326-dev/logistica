"""
Geocodificação sob demanda, com cache.

- Só geocodifica os clientes que aparecem nos quadros (não as 6.000 linhas da
  base): a primeira vez de cada cliente leva ~1,5 s (limite do serviço
  gratuito Nominatim/OpenStreetMap); depois fica no cache para sempre.
- Endereço vem da base de clientes: a exportação do sistema da empresa
  (base-de-clientes.xlsx: ENDERECO + NUMERO, BAIRRO, CIDADE, UF, CEP) e, para o
  que faltar, a base antiga (base-de-clientes1.xlsx: Endereço, Bairro, Cidade, CEP).
- Cliente que estava no cache só pela rua/CEP/cidade é refeito quando a base
  passa a ter o endereço com número (mais preciso). Correção manual nunca.
- Tentativas, da mais precisa para a menos: rua+cidade+CEP -> CEP -> cidade.
  A precisão fica registrada ("endereco", "cep", "cidade").
- Correção manual (arrastar o marcador no mapa) é guardada com
  "manual": true e nunca é sobrescrita.
- Entrega fora da cidade do cadastro (redespacho, outro endereço) usa a
  coordenada da CIDADE de destino do PDF.

Cache: data/geocache.json (dados da empresa — não vai para o GitHub).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from normalizador import normalizar_codigo_cliente, normalizar_texto
import transportadoras

RAIZ = Path(__file__).resolve().parent
ARQUIVO_CACHE = RAIZ / "data" / "geocache.json"
NOMES_BASE_ENDERECO = ("base-de-clientes.xlsx", "base-de-clientes1.xlsx")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "SuperfineLogistica/1.0 (uso interno)"
INTERVALO_SEG = 1.5

_trava = threading.Lock()
_ultima_consulta = 0.0

Buscador = Callable[[dict[str, str]], Optional[tuple[float, float]]]


# ------------------------------------------------------------------- cache
def carregar_cache() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(ARQUIVO_CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def salvar_cache(cache: dict[str, dict[str, Any]]) -> None:
    ARQUIVO_CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARQUIVO_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ARQUIVO_CACHE)


def chave_cliente(codigo: str) -> str:
    return f"CLI:{normalizar_codigo_cliente(codigo)}"


def chave_cidade(cidade: str, uf: str = "") -> str:
    return f"CID:{normalizar_texto(cidade).replace(chr(39), ' ')}|{normalizar_texto(uf)}"


def definir_manual(chave: str, lat: float, lon: float) -> dict[str, Any]:
    with _trava:
        cache = carregar_cache()
        registro = {**cache.get(chave, {}), "lat": float(lat), "lon": float(lon),
                    "precisao": "manual", "manual": True}
        cache[chave] = registro
        salvar_cache(cache)
    return registro


# ------------------------------------------------------------------- endereços
def _sem_acento(texto: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


_cache_base: dict[str, Any] = {}


def _ler_base_endereco(caminho: Path) -> dict[str, dict[str, str]]:
    import openpyxl

    dados: dict[str, dict[str, str]] = {}
    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        linhas = ws.iter_rows(values_only=True)
        cab = [_sem_acento(normalizar_texto(str(c or ""))) for c in next(linhas, [])]
        idx = {n: i for i, n in enumerate(cab)}
        if "CODIGO" not in idx or "ENDERECO" not in idx:
            return {}  # exportação sem endereço
        pegar = lambda l, nome: str(l[idx[nome]] or "").strip() if nome in idx else ""  # noqa: E731
        for linha in linhas:
            codigo = normalizar_codigo_cliente(pegar(linha, "CODIGO"))
            if not codigo:
                continue
            rua, numero = pegar(linha, "ENDERECO"), pegar(linha, "NUMERO")
            if rua and numero and numero.upper() not in ("0", "S/N", "SN"):
                rua = f"{rua}, {numero}"
            dados[codigo] = {
                "endereco": rua,
                "bairro": pegar(linha, "BAIRRO"),
                "cidade": pegar(linha, "CIDADE"),
                "uf": pegar(linha, "UF"),
                "cep": pegar(linha, "CEP"),
            }
    finally:
        wb.close()
    return dados


def enderecos_base() -> dict[str, dict[str, str]]:
    """codigo_cliente -> {endereco, bairro, cidade, uf, cep}: a base nova primeiro, a antiga completa."""
    candidatos = [RAIZ / n for n in NOMES_BASE_ENDERECO if (RAIZ / n).is_file()]
    if not candidatos:
        return {}
    marca = tuple((str(c), c.stat().st_mtime) for c in candidatos)
    if _cache_base.get("marca") == marca:
        return _cache_base["dados"]
    dados: dict[str, dict[str, str]] = {}
    for caminho in candidatos:
        for codigo, reg in _ler_base_endereco(caminho).items():
            atual = dados.setdefault(codigo, {})
            for campo, valor in reg.items():
                if valor and not atual.get(campo):
                    atual[campo] = valor
    _cache_base.update(marca=marca, dados=dados)
    return dados


def precisa_refazer(registro: dict[str, Any] | None, endereco: dict[str, str]) -> bool:
    """Cache feito sem o número (ou só por CEP/cidade) e agora a base tem rua + número."""
    if not registro or registro.get("manual"):
        return False
    rua = endereco.get("endereco", "")
    if "," not in rua or registro.get("base_endereco") == rua:  # sem número / já tentado
        return False
    return registro.get("precisao") != "endereco" or rua not in str(registro.get("consulta", ""))


# ------------------------------------------------------------------- consulta
def buscar_nominatim(params: dict[str, str]) -> Optional[tuple[float, float]]:
    global _ultima_consulta
    with _trava:
        espera = INTERVALO_SEG - (time.time() - _ultima_consulta)
        if espera > 0:
            time.sleep(espera)
        _ultima_consulta = time.time()
    query = {**{k: v for k, v in params.items() if v}, "format": "json", "limit": "1", "countrycodes": "br"}
    req = urllib.request.Request(f"{NOMINATIM_URL}?{urllib.parse.urlencode(query)}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            achados = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        raise ConnectionError("Serviço de mapas indisponível (sem internet ou bloqueado)")
    if not achados:
        return None
    return float(achados[0]["lat"]), float(achados[0]["lon"])


def geocodificar_cliente(
    endereco: dict[str, str], uf: str = "", buscar: Buscador = buscar_nominatim
) -> Optional[dict[str, Any]]:
    cidade, cep = endereco.get("cidade", ""), endereco.get("cep", "").replace(" ", "")
    tentativas = [
        ("endereco", {"street": endereco.get("endereco", ""), "city": cidade, "state": uf, "postalcode": cep}),
        ("cep", {"postalcode": cep, "country": "Brasil"}),
        ("cidade", {"city": cidade, "state": uf, "country": "Brasil"}),
    ]
    for precisao, params in tentativas:
        if precisao == "endereco" and not endereco.get("endereco"):
            continue
        if precisao == "cep" and not cep:
            continue
        if precisao == "cidade" and not cidade:
            continue
        achado = buscar(params)
        if achado:
            return {"lat": achado[0], "lon": achado[1], "precisao": precisao,
                    "consulta": ", ".join(v for v in params.values() if v)}
    return None


# ------------------------------------------------------------------- uso nas linhas
def chave_da_linha(linha: dict[str, Any], base: dict[str, dict[str, str]] | None = None) -> str:
    """Cliente (se a entrega é na cidade do cadastro) ou a cidade de destino do PDF.
    Levar na transportadora: a própria transportadora (endereço da base ou do PDF)."""
    base = enderecos_base() if base is None else base
    if linha.get("tipo_frete") == "ENTREGA_TERCEIRO_HUB" or linha.get("status") == "ENTREGA_TERCEIRO_HUB":
        info = transportadoras.endereco_transportadora(
            str(linha.get("transportadora_codigo") or ""), str(linha.get("transportadora") or "")
        )
        if info.get("cidade"):
            return f"TRP:{info.get('codigo') or normalizar_texto(info.get('nome', ''))}"
        return ""
    entrega = normalizar_codigo_cliente(str(linha.get("entrega_cliente_codigo", "") or ""))
    if entrega and entrega in base:  # remessa: empresa de entrega está na base
        return chave_cliente(entrega)
    codigo = normalizar_codigo_cliente(str(linha.get("cliente_codigo", "")))
    destino = normalizar_texto(str(linha.get("cidade_destino") or linha.get("cidade") or "")).replace("'", " ")
    cadastro = base.get(codigo, {})
    cidade_cad = normalizar_texto(cadastro.get("cidade", "")).replace("'", " ")
    if codigo and cadastro and (not destino or destino == cidade_cad):
        return chave_cliente(codigo)
    return chave_cidade(destino, str(linha.get("estado_destino") or ""))


def coordenada_da_linha(linha: dict[str, Any], cache: dict | None = None, base: dict | None = None) -> Optional[dict]:
    cache = carregar_cache() if cache is None else cache
    return cache.get(chave_da_linha(linha, base))


def geocodificar_linhas(
    linhas: list[dict[str, Any]],
    buscar: Buscador = buscar_nominatim,
    progresso: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Geocodifica o que falta para estas linhas. Retorna um resumo."""
    base = enderecos_base()
    cache = carregar_cache()
    pendentes: dict[str, dict[str, Any]] = {}
    for linha in linhas:
        chave = chave_da_linha(linha, base)
        if not chave or chave in pendentes:
            continue
        novo = chave not in cache
        if not novo and chave.startswith("CLI:"):
            novo = precisa_refazer(cache.get(chave), base.get(chave[4:], {}))
        if novo:
            pendentes[chave] = linha
    estado = {"total": len(pendentes), "feitos": 0, "nao_achados": [], "erro": ""}
    for chave, linha in pendentes.items():
        uf = str(linha.get("estado_destino") or "")
        try:
            if chave.startswith("CLI:"):
                endereco = base.get(chave[4:], {})
                achado = geocodificar_cliente(endereco, endereco.get("uf") or uf, buscar)
            elif chave.startswith("TRP:"):
                info = transportadoras.endereco_transportadora(
                    str(linha.get("transportadora_codigo") or ""), str(linha.get("transportadora") or "")
                )
                achado = geocodificar_cliente(info, info.get("uf") or uf, buscar)
            else:
                cidade = chave[4:].split("|")[0]
                achado = geocodificar_cliente({"cidade": cidade}, uf, buscar)
        except ConnectionError as exc:
            estado["erro"] = str(exc)
            break
        rua_base = base.get(chave[4:], {}).get("endereco", "") if chave.startswith("CLI:") else ""
        if achado:
            if rua_base:
                achado["base_endereco"] = rua_base  # não refaz de novo com o mesmo endereço
            with _trava:
                cache = carregar_cache()
                cache[chave] = achado
                salvar_cache(cache)
        elif chave in cache and rua_base:
            # tentou melhorar e não achou: fica a coordenada antiga, sem tentar de novo
            with _trava:
                cache = carregar_cache()
                if chave in cache:
                    cache[chave]["base_endereco"] = rua_base
                    salvar_cache(cache)
        else:
            estado["nao_achados"].append(linha.get("cliente") or chave)
        estado["feitos"] += 1
        if progresso:
            progresso(dict(estado))
    return estado


# ------------------------------------------------------------------- fábrica
CHAVE_DEPOSITO = "DEPOSITO"
ENDERECO_FABRICA = {
    "endereco": "Rua Roberto Alves de Almeida, 227",
    "cidade": "Santa Bárbara d'Oeste",
    "cep": "13456-136",
}
# Centro de Santa Bárbara d'Oeste — usado até a fábrica ser localizada.
DEPOSITO_PADRAO = (-22.7536, -47.4136)


def deposito(params: dict[str, Any] | None = None) -> tuple[float, float]:
    """Saída dos caminhões: parâmetro 'deposito' > cache (fábrica localizada) > centro da cidade."""
    cfg = (params or {}).get("deposito") or {}
    if cfg.get("lat") is not None and cfg.get("lon") is not None:
        return float(cfg["lat"]), float(cfg["lon"])
    salvo = carregar_cache().get(CHAVE_DEPOSITO)
    if salvo:
        return float(salvo["lat"]), float(salvo["lon"])
    return DEPOSITO_PADRAO


def garantir_deposito(buscar: Buscador = buscar_nominatim) -> None:
    if CHAVE_DEPOSITO in carregar_cache():
        return
    try:
        achado = geocodificar_cliente(ENDERECO_FABRICA, "SP", buscar)
    except ConnectionError:
        return
    if achado:
        with _trava:
            cache = carregar_cache()
            cache[CHAVE_DEPOSITO] = achado
            salvar_cache(cache)
