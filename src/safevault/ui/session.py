from __future__ import annotations

import json
import os
import signal
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from safevault.atomic import atomic_write_bytes
from safevault.db import utc_now_iso
from safevault.paths import ensure_home_layout, get_safevault_home


@dataclass(frozen=True)
class UiSession:
    host: str
    port: int
    token: str
    started_at: str
    pid: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "token": self.token,
            "started_at": self.started_at,
            "pid": self.pid,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> UiSession:
        pid = data.get("pid")
        return cls(
            host=str(data["host"]),
            port=int(str(data["port"])),
            token=str(data["token"]),
            started_at=str(data["started_at"]),
            pid=None if pid is None else int(str(pid)),
        )


def get_ui_session_path() -> Path:
    return get_safevault_home() / "ui-session.json"


def create_ui_session(host: str, port: int, token: str) -> UiSession:
    return UiSession(
        host=host,
        port=port,
        token=token,
        started_at=utc_now_iso(),
        pid=os.getpid(),
    )


def write_ui_session(session: UiSession) -> None:
    ensure_home_layout()
    payload = json.dumps(session.to_dict(), indent=2).encode("utf-8")
    atomic_write_bytes(get_ui_session_path(), payload, mode=0o600)


def read_ui_session() -> UiSession | None:
    path = get_ui_session_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return UiSession.from_dict(data)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def clear_ui_session(session: UiSession | None = None) -> None:
    path = get_ui_session_path()
    if session is not None:
        current = read_ui_session()
        if current is None or current.token != session.token:
            return
    path.unlink(missing_ok=True)


def ui_url(session: UiSession, *, path: str = "/") -> str:
    if path not in {"/", "/storage"}:
        raise ValueError("unsupported SafeVault UI path")
    return f"http://{session.host}:{session.port}{path}?token={session.token}"


def ui_session_reachable(session: UiSession, *, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(ui_url(session), timeout=timeout) as response:
            return response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def request_ui_stop() -> bool:
    """Stop the currently registered local UI after verifying its token endpoint."""

    session = read_ui_session()
    if session is None:
        return False
    if session.pid is None or session.pid == os.getpid():
        return False
    if not ui_session_reachable(session):
        clear_ui_session(session)
        return False
    try:
        os.kill(session.pid, signal.SIGTERM)
    except OSError:
        clear_ui_session(session)
        return False
    clear_ui_session(session)
    return True
