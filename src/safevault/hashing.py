from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

try:
    import blake3 as _blake3
except ImportError:  # pragma: no cover - only used when dev deps are unavailable.
    _blake3 = None  # type: ignore[assignment]


def _new_hasher() -> Any:
    if _blake3 is not None:
        return _blake3.blake3()
    return hashlib.blake2b(digest_size=32)


def hash_bytes(data: bytes) -> str:
    hasher = _new_hasher()
    hasher.update(data)
    return hasher.hexdigest()


def hash_file(path: Path) -> str:
    hasher = _new_hasher()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
