from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from safevault import object_store
from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.errors import SafeVaultError
from safevault.ignore import build_pathspec, is_ignored
from safevault.paths import ensure_home_layout


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
    return f"SYMLINK\n{os.readlink(path)}".encode("utf-8", "surrogateescape")


def _scan_entry(path: Path, file_kind: str) -> tuple[str, int, int, int]:
    stat_result = path.lstat()
    mode = int(stat_result.st_mode)
    mtime_ns = int(stat_result.st_mtime_ns)
    if file_kind == "symlink":
        payload = _symlink_payload(path)
        content_hash = object_store.store_bytes(payload)
        return content_hash, len(payload), mtime_ns, mode
    content_hash = object_store.store_file(path)
    return content_hash, int(stat_result.st_size), mtime_ns, mode


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
            seen.add(rel_path)
            stat_result = item_path.lstat()
            if file_kind == "symlink":
                size = len(_symlink_payload(item_path))
            else:
                size = stat_result.st_size
            mtime_ns = int(stat_result.st_mtime_ns)
            mode = int(stat_result.st_mode)
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

            content_hash, size, mtime_ns, mode = _scan_entry(item_path, file_kind)
            file_id = _upsert_file(
                conn,
                root_id=root_id,
                rel_path=rel_path,
                file_kind=file_kind,
                current_hash=content_hash,
                size=size,
                mtime_ns=mtime_ns,
                mode=mode,
                last_seen_at=utc_now_iso(),
            )

            should_version = True
            if (
                existing
                and existing["status"] == "active"
                and existing["current_hash"] == content_hash
            ):
                should_version = False
            if should_version:
                _insert_version(
                    conn,
                    file_id=file_id,
                    snapshot_id=snapshot_id,
                    rel_path=rel_path,
                    content_hash=content_hash,
                    size=size,
                    mtime_ns=mtime_ns,
                    mode=mode,
                )
                if existing is None:
                    _insert_event(conn, root_id, "created", rel_path)
                elif existing["status"] == "deleted":
                    _insert_event(conn, root_id, "restored", rel_path)
                elif existing["current_hash"] != content_hash:
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
