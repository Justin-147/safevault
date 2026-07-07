from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import suppress
from pathlib import Path

from safevault.atomic import atomic_copy_from_object
from safevault.db import connect, find_containing_root, utc_now_iso
from safevault.errors import (
    FileNotTrackedError,
    ObjectMissingError,
    RootNotFoundError,
    SafeVaultError,
)
from safevault.object_store import has_object, object_path, read_object, verify_object
from safevault.snapshot import create_snapshot, relative_path


def _find_file(conn: sqlite3.Connection, root_id: int, rel_path: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM files WHERE root_id = ? AND rel_path = ?", (root_id, rel_path)
    ).fetchone()
    if row is None:
        raise FileNotTrackedError(f"file has no tracked history: {rel_path}")
    return row


def _find_version(
    conn: sqlite3.Connection, file_id: int, version_id: int | None, latest: bool
) -> sqlite3.Row:
    if latest:
        row = conn.execute(
            """
            SELECT v.*, f.file_kind FROM versions v
            JOIN files f ON f.id = v.file_id
            WHERE v.file_id = ? AND v.is_deleted_marker = 0
            ORDER BY v.id DESC LIMIT 1
            """,
            (file_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT v.*, f.file_kind FROM versions v
            JOIN files f ON f.id = v.file_id
            WHERE v.file_id = ? AND v.id = ?
            """,
            (file_id, version_id),
        ).fetchone()
    if row is None:
        raise FileNotTrackedError("requested version was not found")
    if int(row["is_deleted_marker"]):
        raise SafeVaultError("deleted marker versions cannot be restored")
    if row["content_hash"] is None or not has_object(str(row["content_hash"])):
        raise ObjectMissingError(f"object {row['content_hash']} is missing")
    return row


def _backup_existing(target: Path) -> Path:
    stamp = utc_now_iso().replace(":", "").replace("+", "Z")
    backup = target.with_name(f"{target.name}.safevault-backup-{stamp}")
    if target.is_symlink():
        os.symlink(os.readlink(target), backup)
    elif target.is_file():
        shutil.copy2(target, backup)
    else:
        raise SafeVaultError(f"refusing to overwrite non-file target: {target}")
    return backup


def _restore_symlink(target: Path, payload: bytes) -> None:
    text = payload.decode("utf-8", "surrogateescape")
    if not text.startswith("SYMLINK\n"):
        raise SafeVaultError("invalid symlink payload")
    link_target = text.split("\n", 1)[1]
    if target.exists() or target.is_symlink():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(link_target, target)
    except (OSError, NotImplementedError):
        target.write_bytes(payload)


def _set_metadata(target: Path, mode: int | None, mtime_ns: int | None) -> None:
    if mode is not None and not target.is_symlink():
        with suppress(OSError):
            os.chmod(target, mode & 0o777)
    if mtime_ns is not None:
        with suppress(OSError, NotImplementedError, ValueError):
            os.utime(target, ns=(mtime_ns, mtime_ns), follow_symlinks=False)


def restore_file(
    file_path: Path,
    *,
    latest: bool = False,
    version_id: int | None = None,
    to_path: Path | None = None,
) -> Path:
    if latest == (version_id is not None):
        raise SafeVaultError("choose exactly one of --latest or --version")

    conn = connect()
    try:
        requested = file_path.expanduser().resolve(strict=False)
        root = find_containing_root(conn, requested)
        if root is None:
            raise RootNotFoundError("file is not under a protected root")
        root_path = Path(root.path)
        rel_path = relative_path(root_path, requested)
        file_record = _find_file(conn, root.id, rel_path)
        version = _find_version(conn, int(file_record["id"]), version_id, latest)
        target = (to_path.expanduser().resolve(strict=False) if to_path else requested)

        target_root = find_containing_root(conn, target)
        if target.exists() or target.is_symlink():
            if target_root is not None:
                create_snapshot(Path(target_root.path), reason="pre-restore-overwrite")
            else:
                _backup_existing(target)

        content_hash = str(version["content_hash"])
        if not verify_object(content_hash):
            read_object(content_hash)
        if str(version["file_kind"]) == "symlink":
            _restore_symlink(target, read_object(content_hash))
        else:
            mode = int(version["mode"] or 0) & 0o777
            atomic_copy_from_object(object_path(content_hash), target, mode)
        _set_metadata(
            target,
            int(version["mode"]) if version["mode"] is not None else None,
            int(version["mtime_ns"]) if version["mtime_ns"] is not None else None,
        )
        conn.execute(
            """
            INSERT INTO events(root_id, event_type, rel_path, old_rel_path, detected_at, source)
            VALUES (?, 'restored', ?, NULL, ?, 'restore')
            """,
            (root.id, rel_path, utc_now_iso()),
        )
        conn.commit()
        if target_root is not None:
            create_snapshot(Path(target_root.path), reason="post-restore")
        return target
    finally:
        conn.close()
