from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from safevault import object_store
from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.errors import SafeVaultError
from safevault.ignore import build_pathspec, is_ignored
from safevault.paths import ensure_home_layout
from safevault.symlinks import symlink_payload


@dataclass(frozen=True)
class CapturedEntry:
    file_kind: str
    content_hash: str
    size: int
    mtime_ns: int
    mode: int


@dataclass(frozen=True)
class CaptureFailure:
    reason: Literal["missing", "unreadable", "unstable"]


CaptureResult = CapturedEntry | CaptureFailure


def relative_path(root: Path, path: Path) -> str:
    root_abs = Path(os.path.abspath(root))
    path_abs = Path(os.path.abspath(path))
    return path_abs.relative_to(root_abs).as_posix()


def _iter_trackable(root: Path):
    spec = build_pathspec()
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if is_ignored(root, path, spec):
                        continue
                    try:
                        if entry.is_symlink():
                            yield path, "symlink"
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            yield path, "file"
                    except OSError:
                        continue
        except OSError:
            continue


def _get_file(conn: sqlite3.Connection, root_id: int, rel_path: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM files WHERE root_id = ? AND rel_path = ?", (root_id, rel_path)
    ).fetchone()


def _insert_event(
    conn: sqlite3.Connection,
    root_id: int,
    event_type: str,
    rel_path: str,
    source: str = "snapshot",
    old_rel_path: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO events(root_id, event_type, rel_path, old_rel_path, detected_at, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (root_id, event_type, rel_path, old_rel_path, utc_now_iso(), source),
    )


def _upsert_file(
    conn: sqlite3.Connection,
    *,
    root_id: int,
    rel_path: str,
    file_kind: str,
    current_hash: str | None,
    size: int | None,
    mtime_ns: int | None,
    mode: int | None,
    last_seen_at: str,
) -> int:
    existing = _get_file(conn, root_id, rel_path)
    if existing:
        conn.execute(
            """
            UPDATE files
            SET file_kind = ?, current_hash = ?, size = ?, mtime_ns = ?, mode = ?,
                last_seen_at = ?, status = 'active'
            WHERE id = ?
            """,
            (
                file_kind,
                current_hash,
                size,
                mtime_ns,
                mode,
                last_seen_at,
                int(existing["id"]),
            ),
        )
        return int(existing["id"])
    cur = conn.execute(
        """
        INSERT INTO files(
            root_id, rel_path, file_kind, current_hash, size, mtime_ns, mode,
            last_seen_at, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (root_id, rel_path, file_kind, current_hash, size, mtime_ns, mode, last_seen_at),
    )
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


def _insert_version(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    snapshot_id: int,
    rel_path: str,
    content_hash: str | None,
    size: int | None,
    mtime_ns: int | None,
    mode: int | None,
    is_deleted_marker: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO versions(
            file_id, snapshot_id, rel_path, content_hash, size, mtime_ns, mode,
            captured_at, is_deleted_marker
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            snapshot_id,
            rel_path,
            content_hash,
            size,
            mtime_ns,
            mode,
            utc_now_iso(),
            is_deleted_marker,
        ),
    )


def _symlink_payload(path: Path) -> bytes:
    return symlink_payload(os.readlink(path))


def _stat_signature(stat_result: os.stat_result) -> tuple[int, int, int | None, int | None]:
    inode = getattr(stat_result, "st_ino", None)
    dev = getattr(stat_result, "st_dev", None)
    return int(stat_result.st_size), int(stat_result.st_mtime_ns), inode, dev


def capture_entry_stable(
    path: Path, file_kind: str, max_retries: int = 2
) -> CaptureResult:
    for _attempt in range(max_retries + 1):
        try:
            before = path.lstat()
        except FileNotFoundError:
            return CaptureFailure("missing")
        except PermissionError:
            return CaptureFailure("unreadable")
        except OSError:
            return CaptureFailure("unstable")
        mode = int(before.st_mode)
        if file_kind == "symlink":
            try:
                payload = _symlink_payload(path)
                after = path.lstat()
            except FileNotFoundError:
                return CaptureFailure("missing")
            except PermissionError:
                return CaptureFailure("unreadable")
            except OSError:
                return CaptureFailure("unstable")
            if _stat_signature(before) != _stat_signature(after):
                continue
            content_hash = object_store.store_bytes(payload)
            return CapturedEntry(
                file_kind=file_kind,
                content_hash=content_hash,
                size=len(payload),
                mtime_ns=int(after.st_mtime_ns),
                mode=mode,
            )

        try:
            content_hash = object_store.store_file(path)
            after = path.lstat()
        except FileNotFoundError:
            return CaptureFailure("missing")
        except PermissionError:
            return CaptureFailure("unreadable")
        except OSError:
            return CaptureFailure("unstable")
        if _stat_signature(before) != _stat_signature(after):
            continue
        return CapturedEntry(
            file_kind=file_kind,
            content_hash=content_hash,
            size=int(after.st_size),
            mtime_ns=int(after.st_mtime_ns),
            mode=mode,
        )
    return CaptureFailure("unstable")


def create_snapshot(path: Path, reason: str = "manual", profile: str = "coding") -> int:
    ensure_home_layout()
    root_path = path.expanduser().resolve()
    if not root_path.exists():
        raise SafeVaultError(f"path does not exist: {root_path}")
    if not root_path.is_dir():
        raise SafeVaultError(f"path is not a directory: {root_path}")

    snapshot_id: int | None = None
    conn = connect()
    try:
        root_id = get_or_create_root(conn, root_path, profile)
        started_at = utc_now_iso()
        cur = conn.execute(
            """
            INSERT INTO snapshots(root_id, reason, label, started_at, finished_at, status)
            VALUES (?, ?, NULL, ?, NULL, 'running')
            """,
            (root_id, reason, started_at),
        )
        assert cur.lastrowid is not None
        snapshot_id = int(cur.lastrowid)
        seen: set[str] = set()

        for item_path, file_kind in _iter_trackable(root_path):
            rel_path = relative_path(root_path, item_path)
            try:
                stat_result = item_path.lstat()
            except FileNotFoundError:
                continue
            except PermissionError:
                seen.add(rel_path)
                _insert_event(conn, root_id, "unreadable", rel_path)
                continue
            except OSError:
                seen.add(rel_path)
                _insert_event(conn, root_id, "unstable", rel_path)
                continue
            seen.add(rel_path)
            if file_kind == "symlink":
                try:
                    size = len(_symlink_payload(item_path))
                except OSError:
                    _insert_event(conn, root_id, "unstable", rel_path)
                    continue
            else:
                size = stat_result.st_size
            mtime_ns = int(stat_result.st_mtime_ns)
            existing = _get_file(conn, root_id, rel_path)

            if (
                existing
                and existing["status"] == "active"
                and existing["file_kind"] == file_kind
                and existing["size"] == size
                and existing["mtime_ns"] == mtime_ns
            ):
                conn.execute(
                    "UPDATE files SET last_seen_at = ? WHERE id = ?",
                    (utc_now_iso(), int(existing["id"])),
                )
                continue

            captured = capture_entry_stable(item_path, file_kind)
            if isinstance(captured, CaptureFailure):
                if captured.reason == "missing":
                    seen.discard(rel_path)
                else:
                    _insert_event(conn, root_id, captured.reason, rel_path)
                continue
            file_id = _upsert_file(
                conn,
                root_id=root_id,
                rel_path=rel_path,
                file_kind=file_kind,
                current_hash=captured.content_hash,
                size=captured.size,
                mtime_ns=captured.mtime_ns,
                mode=captured.mode,
                last_seen_at=utc_now_iso(),
            )

            should_version = True
            if (
                existing
                and existing["status"] == "active"
                and existing["current_hash"] == captured.content_hash
            ):
                should_version = False
            if should_version:
                _insert_version(
                    conn,
                    file_id=file_id,
                    snapshot_id=snapshot_id,
                    rel_path=rel_path,
                    content_hash=captured.content_hash,
                    size=captured.size,
                    mtime_ns=captured.mtime_ns,
                    mode=captured.mode,
                )
                if existing is None:
                    _insert_event(conn, root_id, "created", rel_path)
                elif existing["status"] == "deleted":
                    _insert_event(conn, root_id, "restored", rel_path)
                elif existing["current_hash"] != captured.content_hash:
                    _insert_event(conn, root_id, "modified", rel_path)

        active_rows = conn.execute(
            "SELECT * FROM files WHERE root_id = ? AND status = 'active'", (root_id,)
        ).fetchall()
        for row in active_rows:
            rel_path = str(row["rel_path"])
            if rel_path in seen:
                continue
            conn.execute(
                "UPDATE files SET status = 'deleted', last_seen_at = ? WHERE id = ?",
                (utc_now_iso(), int(row["id"])),
            )
            _insert_version(
                conn,
                file_id=int(row["id"]),
                snapshot_id=snapshot_id,
                rel_path=rel_path,
                content_hash=None,
                size=row["size"],
                mtime_ns=row["mtime_ns"],
                mode=row["mode"],
                is_deleted_marker=1,
            )
            _insert_event(conn, root_id, "deleted", rel_path)

        conn.execute(
            "UPDATE snapshots SET status = 'complete', finished_at = ? WHERE id = ?",
            (utc_now_iso(), snapshot_id),
        )
        conn.commit()
        return snapshot_id
    except Exception:
        if snapshot_id is not None:
            conn.execute(
                "UPDATE snapshots SET status = 'failed', finished_at = ? WHERE id = ?",
                (utc_now_iso(), snapshot_id),
            )
            conn.commit()
        raise
    finally:
        conn.close()
