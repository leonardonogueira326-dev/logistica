"""
Vigia: mantém o sistema ligado e em dia sem depender de ninguém.

Chamado pelo ligar_sozinho.bat (que o Windows abre ao entrar no usuário):
- atualiza o código e sincroniza os dados, prepara as telas (só quando o
  código mudou) e liga o servidor;
- se o servidor cair, liga de novo;
- a cada 10 min confere o GitHub: tendo versão nova e ninguém gravando há
  3 min, desliga, atualiza e liga (a tela recarrega sozinha);
- sincroniza os dados 2 min depois de cada mudança e, de qualquer forma,
  a cada 30 min.

Sai com 75 quando o próprio vigia foi atualizado (o .bat abre de novo) e com
0 quando já existe outro vigia rodando. Registro em logs/vigia.log.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PORTA = int(os.environ.get("LOGISTICA_PORTA", "8000"))
PORTA_TRAVA = PORTA + 7919  # só para garantir um vigia por vez
URL = f"http://127.0.0.1:{PORTA}"
CONFERIR_VERSAO_S = 600
SINCRONIZAR_S = 1800
OCIOSO_S = 180
ENVIAR_APOS_S = int(os.environ.get("LOGISTICA_ENVIAR_APOS_S", "120"))
SAIR_REABRIR = 75
WINDOWS = os.name == "nt"


def log(msg: str) -> None:
    linha = f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} {msg}"
    print(linha, flush=True)
    try:
        (RAIZ / "logs").mkdir(exist_ok=True)
        arq = RAIZ / "logs" / "vigia.log"
        if arq.exists() and arq.stat().st_size > 2_000_000:
            arq.replace(arq.with_suffix(".log.1"))
        with open(arq, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def _git(*args: str, timeout: int = 60) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def commit_local() -> str:
    return _git("rev-parse", "HEAD")


def commit_github() -> str:
    """Versão que este PC deve rodar: 'estavel' (testes do GitHub passaram); sem ela, a main."""
    saida = _git("ls-remote", "origin", "refs/heads/estavel", "refs/heads/main")
    refs = {l.split()[1]: l.split()[0] for l in saida.splitlines() if len(l.split()) == 2}
    return refs.get("refs/heads/estavel") or refs.get("refs/heads/main", "")


def rodar_bat(nome: str, timeout: int = 900) -> int:
    """Roda um .bat do sistema (no Windows). Fora dele (testes) não faz nada."""
    if not WINDOWS:
        return 0
    try:
        return subprocess.run(["cmd", "/c", nome], cwd=RAIZ, timeout=timeout,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"falha ao rodar {nome}: {exc}")
        return 1


def saude(timeout: float = 5) -> dict | None:
    try:
        with urllib.request.urlopen(f"{URL}/api/saude", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def ocioso(s: dict | None, agora: datetime | None = None) -> bool:
    """Ninguém gravou nada nos últimos minutos (seguro para reiniciar)."""
    if not s:
        return True
    ultima = ((s.get("banco") or {}).get("ultima_alteracao") or {}).get("quando", "")
    if not ultima:
        return True
    try:
        parado = ((agora or datetime.now()) - datetime.fromisoformat(ultima)).total_seconds()
    except ValueError:
        return True
    return parado >= OCIOSO_S


def ultima_gravacao(s: dict | None) -> datetime | None:
    """Quando o sistema gravou algo pela última vez (o que chegou do outro PC não conta)."""
    alt = ((s or {}).get("banco") or {}).get("ultima_alteracao") or {}
    if alt.get("origem") != "sistema":
        return None
    try:
        return datetime.fromisoformat(alt.get("quando", ""))
    except ValueError:
        return None


def telas_prontas(commit: str) -> bool:
    dist = RAIZ / "route-genius-main" / "dist"
    try:
        return (dist / "client" / "_shell.html").exists() and (dist / ".commit").read_text().strip() == commit
    except OSError:
        return False


def preparar_telas(commit: str) -> None:
    if telas_prontas(commit) or not WINDOWS:
        return
    log("preparando as telas…")
    dist = RAIZ / "route-genius-main" / "dist"
    for _ in range(2):  # antivírus às vezes segura um arquivo: tenta de novo
        shutil.rmtree(dist, ignore_errors=True)
        try:
            with open(RAIZ / "logs" / "build.log", "w", encoding="utf-8", errors="replace") as saida:
                subprocess.run(["cmd", "/c", "npm run build"], cwd=RAIZ / "route-genius-main",
                               stdout=saida, stderr=subprocess.STDOUT, timeout=900)
        except (OSError, subprocess.SubprocessError) as exc:
            log(f"falha ao preparar as telas: {exc}")
        if (dist / "client" / "_shell.html").exists():
            (dist / ".commit").write_text(commit)
            return
    log("NÃO consegui preparar as telas (logs\\build.log) — o servidor sobe mesmo assim")


def liberar_porta() -> None:
    """Fecha um servidor antigo que tenha ficado na porta (ex.: iniciar.bat esquecido aberto)."""
    if not WINDOWS:
        return
    try:
        saida = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return
    for linha in saida.splitlines():
        partes = linha.split()
        if len(partes) >= 5 and partes[1].endswith(f":{PORTA}") and "LISTENING" in partes:
            subprocess.run(["taskkill", "/F", "/PID", partes[-1]], capture_output=True)


def ligar_servidor() -> subprocess.Popen:
    (RAIZ / "logs").mkdir(exist_ok=True)
    saida = open(RAIZ / "logs" / "servidor.log", "a", encoding="utf-8", errors="replace")  # noqa: SIM115
    env = dict(os.environ)
    env.setdefault("LOGISTICA_OLLAMA_MODEL", "qwen2.5:3b")
    env["LOGISTICA_VIGIA"] = "1"
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(PORTA)],
        cwd=RAIZ, stdout=saida, stderr=subprocess.STDOUT, env=env,
    )


def desligar_servidor(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(20)
    except subprocess.TimeoutExpired:
        proc.kill()


def _marca_vigia() -> float:
    try:
        return Path(__file__).stat().st_mtime
    except OSError:
        return 0.0


def ciclo_de_atualizacao() -> str:
    rodar_bat(r"scripts\atualizar_codigo.bat")
    rodar_bat(r"scripts\sincronizar_dados.bat")
    commit = commit_local()
    preparar_telas(commit)
    return commit


def main() -> int:
    trava = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        trava.bind(("127.0.0.1", PORTA_TRAVA))
        trava.listen(1)
    except OSError:
        print("O sistema já está ligado (outro vigia rodando).")
        return 0

    eu = _marca_vigia()
    log("vigia ligado")
    commit = ciclo_de_atualizacao()
    if _marca_vigia() != eu:
        log("o vigia foi atualizado: reabrindo")
        return SAIR_REABRIR
    liberar_porta()
    proc = ligar_servidor()
    log(f"servidor ligado (versão {commit[:7]})")
    quedas = 0
    ultima_versao = ultima_sinc = ligado_em = time.time()
    ultima_olhada = 0.0
    sinc_ate = datetime.now()  # tudo gravado até aqui já foi sincronizado
    pendente = ""

    while True:
        time.sleep(5)
        agora = time.time()

        if proc.poll() is not None:
            if saude() is not None:
                continue  # outro servidor assumiu a porta (iniciar.bat aberto à mão): não briga
            quedas = quedas + 1 if agora - ligado_em < 120 else 1
            espera = min(60, 5 * quedas)
            log(f"servidor caiu (código {proc.returncode}); ligando de novo em {espera}s")
            time.sleep(espera)
            proc = ligar_servidor()
            ligado_em = time.time()
            continue

        # Sincroniza: 2 min depois da última gravação (para o outro PC já receber)
        # e, de qualquer forma, a cada 30 min (para receber o que veio de lá).
        if agora - ultima_olhada >= 30:
            ultima_olhada = agora
            gravou = ultima_gravacao(saude())
            if gravou and gravou > sinc_ate and (datetime.now() - gravou).total_seconds() >= ENVIAR_APOS_S:
                sinc_ate = datetime.now()
                ultima_sinc = 0.0
        if agora - ultima_sinc >= SINCRONIZAR_S:
            ultima_sinc = agora
            sinc_ate = datetime.now()
            try:
                req = urllib.request.Request(f"{URL}/api/sincronizacao", method="POST", data=b"")
                urllib.request.urlopen(req, timeout=10).close()
            except Exception:  # noqa: BLE001
                pass

        if not pendente and agora - ultima_versao >= CONFERIR_VERSAO_S:
            ultima_versao = agora
            remoto = commit_github()
            if remoto and remoto != commit_local():
                pendente = remoto
                log(f"versão nova no GitHub ({remoto[:7]}): atualizo quando ninguém estiver gravando")

        if pendente and ocioso(saude()):
            log("atualizando…")
            desligar_servidor(proc)
            commit = ciclo_de_atualizacao()
            pendente = ""
            ultima_versao = ultima_sinc = time.time()
            if _marca_vigia() != eu:
                log("o vigia foi atualizado: reabrindo")
                return SAIR_REABRIR
            proc = ligar_servidor()
            ligado_em = time.time()
            log(f"servidor ligado (versão {commit[:7]})")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
