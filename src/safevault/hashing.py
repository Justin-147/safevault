from __future__ import annotations

import os
from pathlib import Path

from safevault.symlinks import symlink_payload

try:
    import blake3
except ImportError as exc:  # pragma: no cover - exercised only in broken environments.
    raise RuntimeError(
        "SafeVault requires the 'blake3' package. Install with: pip install -e '.[dev]'"
    ) from exc


def new_hasher() -> blake3.blake3:
    return blake3.blake3()


def hash_bytes(data: bytes) -> str:
    hasher = new_hasher()
    hasher.update(data)
    return hasher.hexdigest()


def hash_file(path: Path) -> str:
    hasher = new_hasher()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def hash_symlink_target(target: str) -> str:
    return hash_bytes(symlink_payload(target))


def hash_symlink(path: Path) -> str:
    return hash_symlink_target(os.readlink(path))


def hash_path_no_follow(path: Path) -> str:
    if path.is_symlink():
        return hash_symlink(path)
    return hash_file(path)
