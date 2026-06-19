"""Persistência de sessões diárias (UUID) em data/sessions/{id}/."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data" / "sessions"

_session_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(session_id: str) -> threading.Lock:
    with _locks_guard:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.RLock()
        return _session_locks[session_id]


class SessionNotFoundError(FileNotFoundError):
    pass


class SessionStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or DATA_ROOT
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "uploads").mkdir(exist_ok=True)
        meta = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "validated": False,
        }
        self._write_json(session_id, "meta.json", meta)
        self._ensure_cadastro(session_id)
        return session_id

    def _ensure_cadastro(self, session_id: str) -> None:
        dest = self._session_dir(session_id)
        for name in (config.ARQUIVO_CADASTRO_CSV, config.ARQUIVO_CADASTRO_XLSX):
            src = PROJECT_ROOT / name
            if src.exists():
                shutil.copy2(src, dest / name)

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    def session_path(self, session_id: str) -> Path:
        path = self._session_dir(session_id)
        if not path.exists():
            raise SessionNotFoundError(f"Sessão não encontrada: {session_id}")
        return path

    def uploads_dir(self, session_id: str) -> Path:
        path = self.session_path(session_id) / "uploads"
        path.mkdir(exist_ok=True)
        return path

    def save_upload(self, session_id: str, filename: str, content: bytes) -> Path:
        dest = self.uploads_dir(session_id) / filename
        dest.write_bytes(content)
        return dest

    def get_meta(self, session_id: str) -> dict[str, Any]:
        return self._read_json(session_id, "meta.json")

    def set_validated(self, session_id: str, validated: bool = True) -> None:
        meta = self.get_meta(session_id)
        meta["validated"] = validated
        meta["validated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(session_id, "meta.json", meta)

    def is_validated(self, session_id: str) -> bool:
        try:
            return bool(self.get_meta(session_id).get("validated", False))
        except SessionNotFoundError:
            return False

    def save_ingestao(self, session_id: str, data: dict[str, Any]) -> None:
        with _lock_for(session_id):
            self._write_json(session_id, "ingestao.json", data)

    def load_ingestao(self, session_id: str) -> Optional[dict[str, Any]]:
        path = self._session_dir(session_id) / "ingestao.json"
        if not path.exists():
            return None
        with _lock_for(session_id):
            with open(path, encoding="utf-8") as f:
                return json.load(f)

    def update_consolidado(
        self,
        session_id: str,
        pedido_norm: str,
        patch: dict[str, Any],
    ) -> bool:
        """Atualiza um consolidado dentro de ingestao.json (thread-safe)."""
        with _lock_for(session_id):
            ingest = self.load_ingestao(session_id)
            if not ingest:
                return False

            found = False
            for item in ingest.get("consolidados", []):
                if (
                    item.get("numero_pedido_norm") == pedido_norm
                    or item.get("numero_pedido") == pedido_norm
                ):
                    item.update(patch)
                    found = True
                    break

            if not found:
                return False

            resumo = ingest.get("resumo", {})
            if isinstance(resumo, dict):
                processando = sum(
                    1
                    for c in ingest.get("consolidados", [])
                    if c.get("status_ia") == config.COD_PROCESSANDO_IA
                )
                resumo["processando_ia"] = str(processando)
                ingest["resumo"] = resumo

            self._write_json(session_id, "ingestao.json", ingest)
            return True

    def save_consolidados_validados(self, session_id: str, data: dict[str, Any]) -> None:
        self._write_json(session_id, "consolidados_validados.json", data)

    def load_consolidados_validados(self, session_id: str) -> Optional[dict[str, Any]]:
        path = self._session_dir(session_id) / "consolidados_validados.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def save_roteirizacao(self, session_id: str, data: dict[str, Any]) -> None:
        self._write_json(session_id, "roteirizacao.json", data)

    def load_roteirizacao(self, session_id: str) -> Optional[dict[str, Any]]:
        path = self._session_dir(session_id) / "roteirizacao.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _read_json(self, session_id: str, name: str) -> dict[str, Any]:
        path = self.session_path(session_id) / name
        if not path.exists():
            raise SessionNotFoundError(f"Arquivo {name} ausente na sessão {session_id}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, session_id: str, name: str, data: dict[str, Any]) -> None:
        path = self.session_path(session_id) / name
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


store = SessionStore()
