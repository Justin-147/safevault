from __future__ import annotations

import os
import secrets
import string
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

from safevault.atomic import fsync_dir, fsync_file
from safevault.errors import ObjectMissingError
from safevault.hashing import hash_bytes, hash_file, new_hasher
from safevault.paths import ensure_home_layout, get_objects_dir, get_tmp_dir
from safevault.symlinks import symlink_payload


def object_path(content_hash: str) -> Path:
    return get_objects_dir() / content_hash[0:2] / content_hash[2:4] / content_hash


def has_object(content_hash: str) -> bool:
    return object_path(content_hash).is_file()


def _store_payload(data: bytes, content_hash: str) -> str:
    ensure_home_layout()
    final = object_path(content_hash)
    if final.exists():
        return content_hash

    tmp = get_tmp_dir() / f".{content_hash}.{secrets.token_hex(8)}.tmp"
    try:
        with tmp.open("wb") as file_obj:
            file_obj.write(data)
            fsync_file(file_obj)
        if hash_file(tmp) != content_hash:
            raise ObjectMissingError("temporary object digest verification failed")
        final.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(tmp, final)
            fsync_dir(final.parent)
        except FileExistsError:
            tmp.unlink(missing_ok=True)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return content_hash


def store_bytes(data: bytes) -> str:
    return _store_payload(data, hash_bytes(data))


def store_file(path: Path) -> str:
    if path.is_symlink():
        target = os.readlink(path)
        return store_bytes(symlink_payload(target))

    ensure_home_layout()
    hasher = new_hasher()
    tmp = get_tmp_dir() / f".object.{secrets.token_hex(16)}.tmp"
    try:
        with path.open("rb") as src, tmp.open("wb") as dest:
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                hasher.update(chunk)
                dest.write(chunk)
            fsync_file(dest)
        content_hash = hasher.hexdigest()
        if hash_file(tmp) != content_hash:
            raise ObjectMissingError("temporary object digest verification failed")
        final = object_path(content_hash)
        if final.exists():
            tmp.unlink(missing_ok=True)
            return content_hash
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, final)
        fsync_dir(final.parent)
        return content_hash
    finally:
        with suppress(OSError):
            if tmp.exists():
                tmp.unlink()


def read_object(content_hash: str) -> bytes:
    path = object_path(content_hash)
    if not path.is_file():
        raise ObjectMissingError(f"object {content_hash} is missing")
    return path.read_bytes()


def open_object(content_hash: str) -> BinaryIO:
    path = object_path(content_hash)
    if not path.is_file():
        raise ObjectMissingError(f"object {content_hash} is missing")
    return path.open("rb")


def _looks_like_hash(name: str) -> bool:
    hex_chars = set(string.hexdigits.lower())
    return len(name) == 64 and all(char in hex_chars for char in name.lower())


def iter_object_hashes() -> Iterator[str]:
    objects = get_objects_dir()
    if not objects.exists():
        return
    for path in objects.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if name.endswith((".tmp", ".partial")) or not _looks_like_hash(name):
            continue
        yield name
