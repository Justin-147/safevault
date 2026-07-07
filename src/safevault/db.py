from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from safevault.errors import SafeVaultError
from safevault.models import Root
from safevault.paths import ensure_home_layout, get_db_path

SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def connect() -> sqlite3.Connection:
    ensure_home_layout()
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    init_schema(conn)
    return conn


def backup_database_to(destination: Path) -> None:
    """Create a transactionally consistent copy of the SafeVault SQLite DB."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    source = connect()
    dest = sqlite3.connect(destination)
    try:
        source.backup(dest)
        result = str(dest.execute("PRAGMA integrity_check").fetchone()[0])
        if result.lower() != "ok":
            raise SafeVaultError(f"database backup integrity check failed: {result}")
        dest.commit()
    finally:
        dest.close()
        source.close()


def init_schema(conn: sqlite3.Connection) -> None:
    create_base_schema_if_missing(conn)
    migrate(conn)
    conn.commit()


def create_base_schema_if_missing(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS roots (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            profile TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            root_id INTEGER NOT NULL,
            rel_path TEXT NOT NULL,
            file_kind TEXT NOT NULL,
            current_hash TEXT,
            size INTEGER,
            mtime_ns INTEGER,
            mode INTEGER,
            last_seen_at TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(root_id, rel_path),
            FOREIGN KEY(root_id) REFERENCES roots(id)
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY,
            root_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            label TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY(root_id) REFERENCES roots(id)
        );

        CREATE TABLE IF NOT EXISTS versions (
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL,
            snapshot_id INTEGER NOT NULL,
            rel_path TEXT NOT NULL,
            content_hash TEXT,
            size INTEGER,
            mtime_ns INTEGER,
            mode INTEGER,
            captured_at TEXT NOT NULL,
            is_deleted_marker INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(file_id) REFERENCES files(id),
            FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            root_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            old_rel_path TEXT,
            detected_at TEXT NOT NULL,
            source TEXT NOT NULL,
            FOREIGN KEY(root_id) REFERENCES roots(id)
        );

        CREATE TABLE IF NOT EXISTS sandboxes (
            id TEXT PRIMARY KEY,
            root_id INTEGER NOT NULL,
            original_path TEXT NOT NULL,
            sandbox_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY(root_id) REFERENCES roots(id)
        );

        CREATE INDEX IF NOT EXISTS idx_files_root_rel ON files(root_id, rel_path);
        CREATE INDEX IF NOT EXISTS idx_versions_file_id ON versions(file_id);
        CREATE INDEX IF NOT EXISTS idx_versions_content_hash ON versions(content_hash);
        CREATE INDEX IF NOT EXISTS idx_events_root_type_time
            ON events(root_id, event_type, detected_at);
        CREATE INDEX IF NOT EXISTS idx_snapshots_root_time ON snapshots(root_id, started_at);
        """
    )


def get_user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {version}")


def migrate(conn: sqlite3.Connection) -> None:
    version = get_user_version(conn)
    if version > SCHEMA_VERSION:
        raise SafeVaultError(
            f"database schema version {version} is newer than supported {SCHEMA_VERSION}"
        )
    if version < SCHEMA_VERSION:
        set_user_version(conn, SCHEMA_VERSION)


def _root_from_row(row: sqlite3.Row | None) -> Root | None:
    if row is None:
        return None
    return Root(
        id=int(row["id"]),
        path=str(row["path"]),
        created_at=str(row["created_at"]),
        profile=str(row["profile"]),
    )


def normalize_path(path: Path) -> str:
    return str(path.expanduser().resolve())


def get_or_create_root(conn: sqlite3.Connection, path: Path, profile: str) -> int:
    normalized = normalize_path(path)
    row = conn.execute("SELECT id FROM roots WHERE path = ?", (normalized,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO roots(path, created_at, profile) VALUES (?, ?, ?)",
        (normalized, utc_now_iso(), profile),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


def get_root_by_path(conn: sqlite3.Connection, path: Path) -> Root | None:
    row = conn.execute("SELECT * FROM roots WHERE path = ?", (normalize_path(path),)).fetchone()
    return _root_from_row(row)


def list_roots(conn: sqlite3.Connection) -> list[Root]:
    rows = conn.execute("SELECT * FROM roots ORDER BY path").fetchall()
    return [root for row in rows if (root := _root_from_row(row)) is not None]


def find_containing_root(conn: sqlite3.Connection, path: Path) -> Root | None:
    candidate = path.expanduser().resolve(strict=False)
    roots = sorted(list_roots(conn), key=lambda root: len(root.path), reverse=True)
    for root in roots:
        root_path = Path(root.path).resolve(strict=False)
        try:
            if candidate == root_path or candidate.is_relative_to(root_path):
                return root
        except ValueError:
            continue
    return None
