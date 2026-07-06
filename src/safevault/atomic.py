from __future__ import annotations

import os
import secrets
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO


def fsync_file(file_obj: BinaryIO) -> None:
    file_obj.flush()
    os.fsync(file_obj.fileno())


def atomic_write_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with tmp.open("wb") as file_obj:
            file_obj.write(data)
            fsync_file(file_obj)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            with suppress(OSError):
                tmp.unlink()


def atomic_copy_from_object(object_path: Path, target_path: Path, mode: int | None = None) -> None:
    data = object_path.read_bytes()
    atomic_write_bytes(target_path, data, mode)
