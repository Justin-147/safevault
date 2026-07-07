from __future__ import annotations

import stat
from pathlib import Path

EXTERNAL_SYMLINK_MARKER = "SAFEVAULT_EXTERNAL_SYMLINK\n"
SNAPSHOT_SYMLINK_MARKER = "SYMLINK\n"


def symlink_payload(target: str) -> bytes:
    return f"{SNAPSHOT_SYMLINK_MARKER}{target}".encode("utf-8", "surrogateescape")


def parse_symlink_payload(data: bytes) -> str | None:
    marker = SNAPSHOT_SYMLINK_MARKER.encode("utf-8")
    if not data.startswith(marker):
        return None
    target = data[len(marker) :].decode("utf-8", "surrogateescape")
    if not target:
        return None
    return target


def external_symlink_placeholder(target: str) -> bytes:
    return f"{EXTERNAL_SYMLINK_MARKER}{target}".encode("utf-8", "surrogateescape")


def parse_external_symlink_placeholder(data: bytes) -> str | None:
    marker = EXTERNAL_SYMLINK_MARKER.encode("utf-8")
    if not data.startswith(marker):
        return None
    target = data[len(marker) :].decode("utf-8", "surrogateescape")
    if not target:
        return None
    return target


def is_external_symlink_placeholder_file(
    path: Path, *, max_bytes: int = 8192
) -> tuple[bool, str | None]:
    try:
        stat_result = path.lstat()
    except OSError:
        return False, None
    if not stat.S_ISREG(stat_result.st_mode):
        return False, None
    try:
        with path.open("rb") as file_obj:
            data = file_obj.read(max_bytes + 1)
    except OSError:
        return False, None
    if len(data) > max_bytes:
        return False, None
    target = parse_external_symlink_placeholder(data)
    return target is not None, target


external_symlink_placeholder_payload = external_symlink_placeholder
