from __future__ import annotations

import os
import secrets
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO


def fsync_file(file_obj: BinaryIO) -> None:
    file_obj.flush()
    os.fsync(file_obj.fileno())


def fsync_dir(path: Path) -> None:
    with suppress(OSError, AttributeError):
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _tmp_for(path: Path) -> Path:
    return path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")


def atomic_copy_bytes(dest: Path, data: bytes, mode: int | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_for(dest)
    try:
        with tmp.open("wb") as file_obj:
            file_obj.write(data)
            fsync_file(file_obj)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, dest)
        fsync_dir(dest.parent)
    finally:
        if tmp.exists():
            with suppress(OSError):
                tmp.unlink()


def atomic_copy_file(src: Path, dest: Path, mode: int | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_for(dest)
    try:
        with src.open("rb") as src_obj, tmp.open("wb") as dest_obj:
            for chunk in iter(lambda: src_obj.read(1024 * 1024), b""):
                dest_obj.write(chunk)
            fsync_file(dest_obj)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, dest)
        fsync_dir(dest.parent)
    finally:
        if tmp.exists():
            with suppress(OSError):
                tmp.unlink()


def atomic_write_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    atomic_copy_bytes(path, data, mode)


def atomic_copy_from_object(object_path: Path, target_path: Path, mode: int | None = None) -> None:
    atomic_copy_file(object_path, target_path, mode)
