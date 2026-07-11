from __future__ import annotations

import os
from pathlib import Path

from safevault.atomic import atomic_write_bytes
from safevault.errors import SafeVaultError


def get_default_safevault_home() -> Path:
    value = os.environ.get("SAFEVAULT_DEFAULT_HOME")
    if value:
        return Path(value).expanduser().resolve()
    return (Path.home() / ".safevault").resolve()


def get_storage_location_file() -> Path:
    value = os.environ.get("SAFEVAULT_LOCATION_FILE")
    if value:
        return Path(value).expanduser().resolve()
    return (Path.home() / ".safevault-location").resolve()


def get_runtime_dir() -> Path:
    value = os.environ.get("SAFEVAULT_RUNTIME_DIR")
    if value:
        return Path(value).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return (Path(local_app_data) / "SafeVault" / "runtime").resolve()
    return (get_storage_location_file().parent / ".safevault-runtime").resolve()


def get_runtime_logs_dir() -> Path:
    return get_runtime_dir() / "logs"


def get_safevault_home() -> Path:
    value = os.environ.get("SAFEVAULT_HOME")
    if value:
        return Path(value).expanduser().resolve()
    location_file = get_storage_location_file()
    if location_file.is_file():
        try:
            configured = location_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SafeVaultError(f"cannot read storage location file: {exc}") from exc
        if not configured:
            raise SafeVaultError("storage location file is empty")
        home = Path(configured).expanduser()
        if not home.is_absolute():
            raise SafeVaultError("configured SafeVault storage location must be absolute")
        resolved = home.resolve(strict=False)
        if resolved.parent == resolved:
            raise SafeVaultError("SafeVault storage location must not be a filesystem root")
        return resolved
    return get_default_safevault_home()


def set_safevault_home_location(path: Path) -> Path:
    if os.environ.get("SAFEVAULT_HOME"):
        raise SafeVaultError(
            "cannot change storage location while SAFEVAULT_HOME override is active"
        )
    resolved = path.expanduser().resolve(strict=False)
    if not resolved.is_absolute() or resolved.parent == resolved:
        raise SafeVaultError("SafeVault storage location must be an absolute non-root path")
    pointer = get_storage_location_file()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(pointer, (str(resolved) + "\n").encode("utf-8"))
    return resolved


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
