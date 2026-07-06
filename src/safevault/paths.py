from __future__ import annotations

import os
from pathlib import Path


def get_safevault_home() -> Path:
    value = os.environ.get("SAFEVAULT_HOME")
    if value:
        return Path(value).expanduser().resolve()
    return (Path.home() / ".safevault").resolve()


def get_db_path() -> Path:
    return get_safevault_home() / "vault.db"


def get_objects_dir() -> Path:
    return get_safevault_home() / "objects"


def get_tmp_dir() -> Path:
    return get_safevault_home() / "tmp"


def get_sandboxes_dir() -> Path:
    return get_safevault_home() / "sandboxes"


def get_logs_dir() -> Path:
    return get_safevault_home() / "logs"


def ensure_home_layout() -> Path:
    home = get_safevault_home()
    for path in (home, get_objects_dir(), get_logs_dir(), get_sandboxes_dir(), get_tmp_dir()):
        path.mkdir(parents=True, exist_ok=True)
    return home
