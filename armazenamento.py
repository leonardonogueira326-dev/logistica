"""
Camada única de armazenamento: todo dado que o sistema grava passa por aqui.

Banco local (SQLite, um arquivo em data/local/logistica.db — nada sai deste PC):
- cada gravação é uma transação: ou grava inteiro ou não grava (acabou o
  risco de arquivo pela metade se o PC desligar no meio);
- guarda as últimas versões de cada documento (dá para voltar atrás);
- registra toda alteração (quando, em qual PC, de onde veio);
- backup diário automático em data/local/backups/.

Enquanto o sistema roda em DOIS PCs, cada documento também é espelhado no
arquivo .json de sempre: é esse arquivo que a sincronização leva de um PC
para o outro. Quando o arquivo muda por fora (chegou do outro PC), a próxima
leitura traz a novidade para o banco. Arquivo corrompido não entra: fica a
versão boa do banco e o arquivo é refeito.

No servidor (um lugar só), basta LOGISTICA_SEM_ESPELHO=1: o banco fica sozinho.
Trocar SQLite por outro banco = trocar este arquivo, e só ele.

Uso:  armazenamento.ler(caminho) / gravar(caminho, dados) / existe / apagar
      python armazenamento.py status      (resumo do banco)
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

RAIZ = Path(__file__).resolve().parent
ARQUIVO_DB = RAIZ / "data" / "local" / "logistica.db"
VERSOES_GUARDADAS = 20          # aprendizado, configuração…
VERSOES_GUARDADAS_QUADRO = 5    # documentos dos quadros do dia (maiores)
DIAS_VERSOES_QUADRO = 30
BACKUPS_GUARDADOS = 14

_trava = threading.RLock()
_pronto: set[str] = set()
_backup_feito = ""

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    chave TEXT PRIMARY KEY,
    conteudo TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    arq_mtime INTEGER,
    arq_tamanho INTEGER,
    espelho_pendente INTEGER NOT NULL DEFAULT 0,
    so_banco INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS versoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave TEXT NOT NULL,
    conteudo TEXT NOT NULL,
    substituido_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS versoes_chave ON versoes (chave, id);
CREATE TABLE IF NOT EXISTS alteracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quando TEXT NOT NULL,
    pc TEXT NOT NULL,
    chave TEXT NOT NULL,
    origem TEXT NOT NULL,
    tamanho INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS info (nome TEXT PRIMARY KEY, valor TEXT NOT NULL);
INSERT OR IGNORE INTO info (nome, valor) VALUES ('esquema', '1');
"""


# ------------------------------------------------------------------ básico
def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _chave(caminho: Path | str) -> str | None:
    """Caminho relativo à pasta do sistema; None = fora dela (testes, exportações): só arquivo."""
    if os.environ.get("LOGISTICA_SEM_BANCO"):
        return None
    try:
        return Path(caminho).resolve().relative_to(Path(RAIZ).resolve()).as_posix()
    except ValueError:
        return None


def _espelha() -> bool:
    return not os.environ.get("LOGISTICA_SEM_ESPELHO")


@contextmanager
def _conexao() -> Iterator[sqlite3.Connection]:
    db = Path(ARQUIVO_DB)
    with _trava:
        if str(db) not in _pronto:
            db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            if str(db) not in _pronto:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_ESQUEMA)
                _pronto.add(str(db))
            conn.execute("PRAGMA synchronous=NORMAL")
            with conn:  # transação: commit no fim, rollback se der erro
                yield conn
        finally:
            conn.close()


def _texto(dados: Any, indent: int | None = 2) -> str:
    return json.dumps(dados, ensure_ascii=False, indent=indent)


def _gravar_arquivo(caminho: Path, texto: str) -> None:
    """Grava inteiro ou não grava (arquivo temporário + troca), com novas tentativas (antivírus)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".gravando")
    ultimo: OSError | None = None
    for tentativa in range(4):
        try:
            tmp.write_text(texto, encoding="utf-8")
            os.replace(tmp, caminho)
            return
        except OSError as exc:
            ultimo = exc
            time.sleep(0.15 * (tentativa + 1))
    raise ultimo  # type: ignore[misc]


def _stat(caminho: Path) -> tuple[int, int] | None:
    try:
        st = caminho.stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


def _registrar(conn: sqlite3.Connection, chave: str, origem: str, tamanho: int) -> None:
    conn.execute(
        "INSERT INTO alteracoes (quando, pc, chave, origem, tamanho) VALUES (?,?,?,?,?)",
        (_agora(), socket.gethostname(), chave, origem, tamanho),
    )


def _guardar_versao(conn: sqlite3.Connection, chave: str, conteudo: str) -> None:
    conn.execute("INSERT INTO versoes (chave, conteudo, substituido_em) VALUES (?,?,?)", (chave, conteudo, _agora()))
    limite = VERSOES_GUARDADAS_QUADRO if chave.startswith("data/sessions/") else VERSOES_GUARDADAS
    conn.execute(
        "DELETE FROM versoes WHERE chave=? AND id NOT IN (SELECT id FROM versoes WHERE chave=? ORDER BY id DESC LIMIT ?)",
        (chave, chave, limite),
    )


def _espelhar(conn: sqlite3.Connection, chave: str, caminho: Path, texto: str) -> None:
    try:
        _gravar_arquivo(caminho, texto)
        st = _stat(caminho)
        conn.execute(
            "UPDATE documentos SET arq_mtime=?, arq_tamanho=?, espelho_pendente=0 WHERE chave=?",
            (st[0] if st else None, st[1] if st else None, chave),
        )
    except OSError:
        # o banco já tem o dado; o arquivo é refeito na próxima leitura/gravação
        conn.execute("UPDATE documentos SET espelho_pendente=1 WHERE chave=?", (chave,))


def _atual(conn: sqlite3.Connection, chave: str, caminho: Path) -> sqlite3.Row | None:
    """Linha do documento, já conciliada com o arquivo (que pode ter chegado do outro PC)."""
    linha = conn.execute("SELECT * FROM documentos WHERE chave=?", (chave,)).fetchone()
    if linha is not None and (linha["so_banco"] or not _espelha()):
        return linha
    st = _stat(caminho)
    if linha is None:
        if st is None:
            return None
        texto = caminho.read_text(encoding="utf-8-sig")
        json.loads(texto)  # arquivo inválido: quem chamou trata (JSONDecodeError)
        conn.execute(
            "INSERT INTO documentos (chave, conteudo, atualizado_em, arq_mtime, arq_tamanho) VALUES (?,?,?,?,?)",
            (chave, texto, _agora(), st[0], st[1]),
        )
        _registrar(conn, chave, "arquivo", len(texto))
        return conn.execute("SELECT * FROM documentos WHERE chave=?", (chave,)).fetchone()
    if linha["espelho_pendente"]:
        _espelhar(conn, chave, caminho, linha["conteudo"])
        return linha
    if st is None:
        # o arquivo foi apagado por fora (ex.: quadro limpo no outro PC)
        _guardar_versao(conn, chave, linha["conteudo"])
        conn.execute("DELETE FROM documentos WHERE chave=?", (chave,))
        _registrar(conn, chave, "apagado_fora", 0)
        return None
    if st != (linha["arq_mtime"], linha["arq_tamanho"]):
        try:
            texto = caminho.read_text(encoding="utf-8-sig")
            json.loads(texto)
        except (OSError, ValueError):
            # arquivo corrompido (ex.: sincronização pela metade): vale o banco, refaz o arquivo
            _registrar(conn, chave, "arquivo_invalido", 0)
            _espelhar(conn, chave, caminho, linha["conteudo"])
            return linha
        if texto != linha["conteudo"]:
            _guardar_versao(conn, chave, linha["conteudo"])
            _registrar(conn, chave, "sincronizacao", len(texto))
        conn.execute(
            "UPDATE documentos SET conteudo=?, atualizado_em=?, arq_mtime=?, arq_tamanho=? WHERE chave=?",
            (texto, _agora() if texto != linha["conteudo"] else linha["atualizado_em"], st[0], st[1], chave),
        )
        return conn.execute("SELECT * FROM documentos WHERE chave=?", (chave,)).fetchone()
    return linha


# ------------------------------------------------------------------ uso
def ler(caminho: Path | str) -> Any:
    """Conteúdo do documento. FileNotFoundError se não existe; JSONDecodeError se o arquivo é inválido."""
    caminho = Path(caminho)
    chave = _chave(caminho)
    if chave is None:
        return json.loads(caminho.read_text(encoding="utf-8-sig"))
    with _conexao() as conn:
        linha = _atual(conn, chave, caminho)
        if linha is None:
            raise FileNotFoundError(str(caminho))
        return json.loads(linha["conteudo"])


def ler_ou(caminho: Path | str, padrao: Any = None) -> Any:
    try:
        return ler(caminho)
    except (OSError, ValueError):
        return padrao


def existe(caminho: Path | str) -> bool:
    caminho = Path(caminho)
    chave = _chave(caminho)
    if chave is None:
        return caminho.exists()
    try:
        with _conexao() as conn:
            return _atual(conn, chave, caminho) is not None
    except ValueError:
        return True  # existe, mas o arquivo está inválido


def marca(caminho: Path | str) -> str:
    """Muda sempre que o documento muda (para quem guarda cópia em memória)."""
    caminho = Path(caminho)
    chave = _chave(caminho)
    if chave is None:
        return str(_stat(caminho))
    try:
        with _conexao() as conn:
            linha = _atual(conn, chave, caminho)
            return f"{linha['atualizado_em']}|{len(linha['conteudo'])}|{linha['arq_mtime']}" if linha else ""
    except ValueError:
        return "invalido"


_marcas: dict[str, tuple[float, str]] = {}


def marca_rapida(caminho: Path | str, validade: float = 1.0) -> str:
    """marca() consultada no máximo uma vez por segundo (para cópias em memória muito lidas)."""
    k = str(caminho)
    agora = time.monotonic()
    guardada = _marcas.get(k)
    if guardada and agora - guardada[0] < validade:
        return guardada[1]
    m = marca(caminho)
    _marcas[k] = (agora, m)
    return m


def gravar(caminho: Path | str, dados: Any, indent: int | None = 2, so_banco: bool = False) -> None:
    """Grava o documento (transação) e, se for o caso, espelha no arquivo .json."""
    caminho = Path(caminho)
    texto = _texto(dados, indent)
    chave = _chave(caminho)
    if chave is None:
        _gravar_arquivo(caminho, texto)
        return
    _marcas.pop(str(caminho), None)
    with _conexao() as conn:
        antes = conn.execute("SELECT conteudo FROM documentos WHERE chave=?", (chave,)).fetchone()
        mudou = antes is None or antes["conteudo"] != texto
        if mudou:
            if antes is not None and not so_banco:
                _guardar_versao(conn, chave, antes["conteudo"])
            conn.execute(
                "INSERT INTO documentos (chave, conteudo, atualizado_em, so_banco) VALUES (?,?,?,?) "
                "ON CONFLICT(chave) DO UPDATE SET conteudo=excluded.conteudo, atualizado_em=excluded.atualizado_em, "
                "so_banco=excluded.so_banco",
                (chave, texto, _agora(), 1 if so_banco else 0),
            )
            if not so_banco:
                _registrar(conn, chave, "sistema", len(texto))
        if not so_banco and _espelha():
            linha = conn.execute("SELECT arq_mtime, arq_tamanho FROM documentos WHERE chave=?", (chave,)).fetchone()
            if mudou or _stat(caminho) != (linha["arq_mtime"], linha["arq_tamanho"]):
                _espelhar(conn, chave, caminho, texto)
    _backup_se_virou_o_dia()


def apagar(caminho: Path | str) -> None:
    caminho = Path(caminho)
    chave = _chave(caminho)
    if chave is not None:
        with _conexao() as conn:
            antes = conn.execute("SELECT conteudo, so_banco FROM documentos WHERE chave=?", (chave,)).fetchone()
            if antes is not None:
                if not antes["so_banco"]:
                    _guardar_versao(conn, chave, antes["conteudo"])
                    _registrar(conn, chave, "apagado", 0)
                conn.execute("DELETE FROM documentos WHERE chave=?", (chave,))
    try:
        caminho.unlink()
    except OSError:
        pass


def versoes(caminho: Path | str) -> list[dict[str, Any]]:
    """Versões anteriores guardadas (mais nova primeiro): [{id, substituido_em, tamanho}]."""
    chave = _chave(caminho)
    if chave is None:
        return []
    with _conexao() as conn:
        return [
            {"id": r["id"], "substituido_em": r["substituido_em"], "tamanho": len(r["conteudo"])}
            for r in conn.execute("SELECT * FROM versoes WHERE chave=? ORDER BY id DESC", (chave,))
        ]


def restaurar(caminho: Path | str, id_versao: int) -> Any:
    """Volta o documento para uma versão guardada (a atual vira versão também)."""
    chave = _chave(caminho)
    if chave is None:
        raise FileNotFoundError("Sem banco para este caminho.")
    with _conexao() as conn:
        r = conn.execute("SELECT conteudo FROM versoes WHERE id=? AND chave=?", (id_versao, chave)).fetchone()
    if r is None:
        raise FileNotFoundError(f"Versão {id_versao} não encontrada.")
    dados = json.loads(r["conteudo"])
    gravar(caminho, dados)
    return dados


# ------------------------------------------------------------------ backup
def backup(destino: Path | None = None) -> Path | None:
    """Cópia consistente do banco (pode rodar com o sistema em uso)."""
    db = Path(ARQUIVO_DB)
    if os.environ.get("LOGISTICA_SEM_BANCO") or not db.exists():
        return None
    destino = destino or db.parent / "backups" / f"logistica-{date.today().isoformat()}.db"
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".copiando")
    with _trava:
        origem = sqlite3.connect(str(db), timeout=30)
        copia = sqlite3.connect(str(tmp))
        try:
            origem.backup(copia)
        finally:
            copia.close()
            origem.close()
    os.replace(tmp, destino)
    antigos = sorted(destino.parent.glob("logistica-*.db"))[:-BACKUPS_GUARDADOS]
    for velho in antigos:
        try:
            velho.unlink()
        except OSError:
            pass
    return destino


def _backup_se_virou_o_dia() -> None:
    """Um backup por dia, feito sozinho na primeira gravação do dia (em segundo plano)."""
    global _backup_feito
    hoje = date.today().isoformat()
    if _backup_feito == hoje or os.environ.get("LOGISTICA_SEM_BANCO"):
        return
    _backup_feito = hoje
    if (Path(ARQUIVO_DB).parent / "backups" / f"logistica-{hoje}.db").exists():
        return

    def tarefa() -> None:
        try:
            backup()
            corte = (datetime.now() - timedelta(days=DIAS_VERSOES_QUADRO)).isoformat(timespec="seconds")
            with _conexao() as conn:
                conn.execute("DELETE FROM versoes WHERE chave LIKE 'data/sessions/%' AND substituido_em < ?", (corte,))
                conn.execute("DELETE FROM alteracoes WHERE quando < ?",
                             ((datetime.now() - timedelta(days=365)).isoformat(timespec="seconds"),))
        except Exception:  # noqa: BLE001 — backup nunca derruba o sistema
            pass

    threading.Thread(target=tarefa, daemon=True).start()


def importar_tudo() -> int:
    """Traz para o banco todos os documentos que ainda só existem em arquivo (1ª vez / pós-sincronização)."""
    if os.environ.get("LOGISTICA_SEM_BANCO") or not _espelha():
        return 0
    dados = Path(RAIZ) / "data"
    arquivos = [*dados.glob("*.json"), *dados.glob("historico/*.json"), *dados.glob("sessions/*/*.json")]
    vistos = 0
    for arq in arquivos:
        try:
            if existe(arq):
                vistos += 1
        except (OSError, sqlite3.Error):
            pass
    return vistos


def status() -> dict[str, Any]:
    """Resumo para a página de saúde."""
    db = Path(ARQUIVO_DB)
    if os.environ.get("LOGISTICA_SEM_BANCO"):
        return {"ligado": False}
    with _conexao() as conn:
        docs = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(espelho_pendente),0) p FROM documentos").fetchone()
        ultima = conn.execute("SELECT quando, pc, chave, origem FROM alteracoes ORDER BY id DESC LIMIT 1").fetchone()
        integro = conn.execute("PRAGMA quick_check").fetchone()[0]
    backups = sorted((db.parent / "backups").glob("logistica-*.db"))
    return {
        "ligado": True,
        "arquivo": str(db),
        "tamanho_mb": round(db.stat().st_size / 1e6, 2) if db.exists() else 0,
        "documentos": docs["n"],
        "espelhos_pendentes": docs["p"],
        "integridade": integro,
        "ultima_alteracao": dict(ultima) if ultima else None,
        "ultimo_backup": backups[-1].name if backups else "",
        "backups": len(backups),
    }


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["backup"]:
        print(backup())
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
