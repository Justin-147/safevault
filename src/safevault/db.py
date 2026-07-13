from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from safevault.errors import SafeVaultError
from safevault.models import ProtectionPolicy, Root
from safevault.paths import ensure_home_layout, get_db_path

SCHEMA_VERSION = 6


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
    ensure_migrations_table(conn)
    version = get_user_version(conn)
    if version > SCHEMA_VERSION:
        raise SafeVaultError(
            f"database schema version {version} is newer than supported {SCHEMA_VERSION}"
        )
    if version < 1:
        record_migration(conn, 1)
        set_user_version(conn, 1)
        version = 1
    if version < 2:
        migrate_to_v2(conn)
        set_user_version(conn, 2)
        version = 2
    if version < 3:
        migrate_to_v3(conn)
        set_user_version(conn, 3)
        version = 3
    if version < 4:
        migrate_to_v4(conn)
        set_user_version(conn, 4)
        version = 4
    if version < 5:
        migrate_to_v5(conn)
        set_user_version(conn, 5)
        version = 5
    if version < 6:
        migrate_to_v6(conn)
        set_user_version(conn, 6)


def ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def record_migration(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version, applied_at)
        VALUES (?, ?)
        """,
        (version, utc_now_iso()),
    )


def migrate_to_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS protection_policies (
            id INTEGER PRIMARY KEY,
            root_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            profile TEXT NOT NULL,
            auto_snapshot INTEGER NOT NULL DEFAULT 1,
            watch_enabled INTEGER NOT NULL DEFAULT 1,
            hourly_snapshot INTEGER NOT NULL DEFAULT 1,
            daily_snapshot INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            paused_until TEXT,
            FOREIGN KEY(root_id) REFERENCES roots(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_protection_policies_root
            ON protection_policies(root_id);

        CREATE TABLE IF NOT EXISTS daemon_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            pid INTEGER,
            status TEXT NOT NULL,
            started_at TEXT,
            last_heartbeat_at TEXT,
            message TEXT
        );

        CREATE TABLE IF NOT EXISTS change_batches (
            id TEXT PRIMARY KEY,
            root_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            last_event_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            created_count INTEGER NOT NULL DEFAULT 0,
            modified_count INTEGER NOT NULL DEFAULT 0,
            deleted_count INTEGER NOT NULL DEFAULT 0,
            snapshot_id INTEGER,
            FOREIGN KEY(root_id) REFERENCES roots(id),
            FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
        );

        CREATE INDEX IF NOT EXISTS idx_change_batches_root_status
            ON change_batches(root_id, status, last_event_at);

        CREATE TABLE IF NOT EXISTS backup_jobs (
            id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            target_path TEXT NOT NULL,
            archive_path TEXT,
            object_count INTEGER,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            read_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_notifications_created
            ON notifications(created_at);
        """
    )
    now = utc_now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO protection_policies(
            root_id, enabled, profile, auto_snapshot, watch_enabled,
            hourly_snapshot, daily_snapshot, created_at, updated_at, paused_until
        )
        SELECT id, 1, profile, 1, 1, 1, 1, ?, ?, NULL
        FROM roots
        """,
        (now, now),
    )
    record_migration(conn, 2)


def migrate_to_v3(conn: sqlite3.Connection) -> None:
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(daemon_state)").fetchall()
    }
    if "stopped_at" not in columns:
        conn.execute("ALTER TABLE daemon_state ADD COLUMN stopped_at TEXT")
    record_migration(conn, 3)


def migrate_to_v4(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS file_events (
            id INTEGER PRIMARY KEY,
            root_id INTEGER NOT NULL,
            file_id INTEGER,
            snapshot_id INTEGER,
            event_type TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            old_rel_path TEXT,
            detected_at TEXT NOT NULL,
            source TEXT NOT NULL,
            details TEXT,
            FOREIGN KEY(root_id) REFERENCES roots(id),
            FOREIGN KEY(file_id) REFERENCES files(id),
            FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
        );

        CREATE INDEX IF NOT EXISTS idx_file_events_root_time
            ON file_events(root_id, detected_at);
        CREATE INDEX IF NOT EXISTS idx_file_events_path_time
            ON file_events(root_id, rel_path, detected_at);

        CREATE TABLE IF NOT EXISTS version_timeline (
            id INTEGER PRIMARY KEY,
            root_id INTEGER NOT NULL,
            file_id INTEGER NOT NULL,
            version_id INTEGER NOT NULL,
            snapshot_id INTEGER NOT NULL,
            rel_path TEXT NOT NULL,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            FOREIGN KEY(root_id) REFERENCES roots(id),
            FOREIGN KEY(file_id) REFERENCES files(id),
            FOREIGN KEY(version_id) REFERENCES versions(id),
            FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
        );

        CREATE INDEX IF NOT EXISTS idx_version_timeline_root_time
            ON version_timeline(root_id, occurred_at);
        CREATE INDEX IF NOT EXISTS idx_version_timeline_path_time
            ON version_timeline(root_id, rel_path, occurred_at);

        CREATE TABLE IF NOT EXISTS restore_points (
            id INTEGER PRIMARY KEY,
            root_id INTEGER NOT NULL,
            snapshot_id INTEGER NOT NULL UNIQUE,
            label TEXT,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            source TEXT NOT NULL,
            important INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(root_id) REFERENCES roots(id),
            FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
        );

        CREATE INDEX IF NOT EXISTS idx_restore_points_root_time
            ON restore_points(root_id, created_at);
        """
    )
    conn.execute(
        """
        INSERT INTO file_events(
            root_id, file_id, snapshot_id, event_type, rel_path, old_rel_path,
            detected_at, source, details
        )
        SELECT
            e.root_id,
            f.id,
            NULL,
            e.event_type,
            e.rel_path,
            e.old_rel_path,
            e.detected_at,
            e.source,
            NULL
        FROM events e
        LEFT JOIN files f ON f.root_id = e.root_id AND f.rel_path = e.rel_path
        WHERE NOT EXISTS (
            SELECT 1 FROM file_events fe
            WHERE fe.root_id = e.root_id
              AND fe.event_type = e.event_type
              AND fe.rel_path = e.rel_path
              AND fe.detected_at = e.detected_at
        )
        """
    )
    conn.execute(
        """
        INSERT INTO version_timeline(
            root_id, file_id, version_id, snapshot_id, rel_path, event_type,
            title, occurred_at
        )
        SELECT
            f.root_id,
            v.file_id,
            v.id,
            v.snapshot_id,
            v.rel_path,
            CASE WHEN v.is_deleted_marker = 1 THEN 'deleted' ELSE 'version' END,
            CASE WHEN v.is_deleted_marker = 1
                 THEN 'Deleted ' || v.rel_path
                 ELSE 'Saved ' || v.rel_path
            END,
            v.captured_at
        FROM versions v
        JOIN files f ON f.id = v.file_id
        WHERE NOT EXISTS (
            SELECT 1 FROM version_timeline vt WHERE vt.version_id = v.id
        )
        """
    )
    conn.execute(
        """
        INSERT INTO restore_points(
            root_id, snapshot_id, label, reason, created_at, source, important
        )
        SELECT
            root_id,
            id,
            label,
            reason,
            COALESCE(finished_at, started_at),
            reason,
            CASE
                WHEN reason LIKE '%checkpoint%' OR label IS NOT NULL THEN 1
                ELSE 0
            END
        FROM snapshots
        WHERE status = 'complete'
          AND NOT EXISTS (
              SELECT 1 FROM restore_points rp WHERE rp.snapshot_id = snapshots.id
          )
        """
    )
    record_migration(conn, 4)


def migrate_to_v5(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ai_change_sessions (
            id INTEGER PRIMARY KEY,
            root_id INTEGER NOT NULL,
            sandbox_id TEXT,
            tool_name TEXT NOT NULL,
            command TEXT NOT NULL,
            before_snapshot_id INTEGER,
            after_snapshot_id INTEGER,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            created_count INTEGER NOT NULL DEFAULT 0,
            modified_count INTEGER NOT NULL DEFAULT 0,
            deleted_count INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(root_id) REFERENCES roots(id),
            FOREIGN KEY(sandbox_id) REFERENCES sandboxes(id),
            FOREIGN KEY(before_snapshot_id) REFERENCES snapshots(id),
            FOREIGN KEY(after_snapshot_id) REFERENCES snapshots(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ai_change_sessions_root_time
            ON ai_change_sessions(root_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_ai_change_sessions_sandbox
            ON ai_change_sessions(sandbox_id);
        """
    )
    record_migration(conn, 5)


def migrate_to_v6(conn: sqlite3.Connection) -> None:
    """Index child foreign keys used by large-root history removal."""
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_versions_snapshot_id
            ON versions(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_change_batches_snapshot_id
            ON change_batches(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_file_events_file_id
            ON file_events(file_id);
        CREATE INDEX IF NOT EXISTS idx_file_events_snapshot_id
            ON file_events(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_version_timeline_file_id
            ON version_timeline(file_id);
        CREATE INDEX IF NOT EXISTS idx_version_timeline_version_id
            ON version_timeline(version_id);
        CREATE INDEX IF NOT EXISTS idx_version_timeline_snapshot_id
            ON version_timeline(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_ai_change_sessions_before_snapshot_id
            ON ai_change_sessions(before_snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_ai_change_sessions_after_snapshot_id
            ON ai_change_sessions(after_snapshot_id);
        """
    )
    record_migration(conn, 6)


def insert_ai_change_session(
    conn: sqlite3.Connection,
    *,
    root_id: int,
    sandbox_id: str,
    tool_name: str,
    command: str,
    before_snapshot_id: int | None,
    status: str,
    created_count: int,
    modified_count: int,
    deleted_count: int,
) -> None:
    conn.execute(
        """
        INSERT INTO ai_change_sessions(
            root_id, sandbox_id, tool_name, command, before_snapshot_id,
            after_snapshot_id, created_at, completed_at, status,
            created_count, modified_count, deleted_count
        )
        VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?)
        """,
        (
            root_id,
            sandbox_id,
            tool_name,
            command,
            before_snapshot_id,
            utc_now_iso(),
            status,
            created_count,
            modified_count,
            deleted_count,
        ),
    )


def get_ai_change_session(
    conn: sqlite3.Connection, sandbox_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM ai_change_sessions
        WHERE sandbox_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (sandbox_id,),
    ).fetchone()


def complete_ai_change_session(
    conn: sqlite3.Connection,
    *,
    sandbox_id: str,
    after_snapshot_id: int | None,
    status: str,
) -> None:
    conn.execute(
        """
        UPDATE ai_change_sessions
        SET after_snapshot_id = ?, completed_at = ?, status = ?
        WHERE sandbox_id = ?
        """,
        (after_snapshot_id, utc_now_iso(), status, sandbox_id),
    )


def insert_file_event(
    conn: sqlite3.Connection,
    *,
    root_id: int,
    event_type: str,
    rel_path: str,
    source: str,
    old_rel_path: str | None = None,
    file_id: int | None = None,
    snapshot_id: int | None = None,
    detected_at: str | None = None,
    details: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO file_events(
            root_id, file_id, snapshot_id, event_type, rel_path, old_rel_path,
            detected_at, source, details
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            root_id,
            file_id,
            snapshot_id,
            event_type,
            rel_path,
            old_rel_path,
            detected_at or utc_now_iso(),
            source,
            details,
        ),
    )


def insert_version_timeline(
    conn: sqlite3.Connection,
    *,
    root_id: int,
    file_id: int,
    version_id: int,
    snapshot_id: int,
    rel_path: str,
    event_type: str,
    occurred_at: str | None = None,
) -> None:
    title = _timeline_title(event_type, rel_path)
    conn.execute(
        """
        INSERT INTO version_timeline(
            root_id, file_id, version_id, snapshot_id, rel_path, event_type,
            title, occurred_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            root_id,
            file_id,
            version_id,
            snapshot_id,
            rel_path,
            event_type,
            title,
            occurred_at or utc_now_iso(),
        ),
    )


def insert_restore_point(
    conn: sqlite3.Connection,
    *,
    root_id: int,
    snapshot_id: int,
    reason: str,
    label: str | None = None,
    created_at: str | None = None,
    source: str | None = None,
    important: bool = False,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO restore_points(
            root_id, snapshot_id, label, reason, created_at, source, important
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            root_id,
            snapshot_id,
            label,
            reason,
            created_at or utc_now_iso(),
            source or reason,
            1 if important else 0,
        ),
    )


def _timeline_title(event_type: str, rel_path: str) -> str:
    labels = {
        "created": "Created",
        "modified": "Modified",
        "deleted": "Deleted",
        "restored": "Restored",
        "version": "Saved",
    }
    return f"{labels.get(event_type, event_type.title())} {rel_path}"


def _root_from_row(row: sqlite3.Row | None) -> Root | None:
    if row is None:
        return None
    return Root(
        id=int(row["id"]),
        path=str(row["path"]),
        created_at=str(row["created_at"]),
        profile=str(row["profile"]),
    )


def _policy_from_row(row: sqlite3.Row | None) -> ProtectionPolicy | None:
    if row is None:
        return None
    return ProtectionPolicy(
        id=int(row["policy_id"]),
        root_id=int(row["root_id"]),
        root_path=str(row["root_path"]),
        enabled=bool(int(row["enabled"])),
        profile=str(row["profile"]),
        auto_snapshot=bool(int(row["auto_snapshot"])),
        watch_enabled=bool(int(row["watch_enabled"])),
        hourly_snapshot=bool(int(row["hourly_snapshot"])),
        daily_snapshot=bool(int(row["daily_snapshot"])),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        paused_until=None if row["paused_until"] is None else str(row["paused_until"]),
    )


def normalize_path(path: Path) -> str:
    return str(path.expanduser().resolve())


def get_or_create_root(conn: sqlite3.Connection, path: Path, profile: str) -> int:
    normalized = normalize_path(path)
    row = conn.execute("SELECT id FROM roots WHERE path = ?", (normalized,)).fetchone()
    if row:
        root_id = int(row["id"])
        ensure_protection_policy(conn, root_id, profile)
        conn.commit()
        return root_id
    cur = conn.execute(
        "INSERT INTO roots(path, created_at, profile) VALUES (?, ?, ?)",
        (normalized, utc_now_iso(), profile),
    )
    assert cur.lastrowid is not None
    root_id = int(cur.lastrowid)
    ensure_protection_policy(conn, root_id, profile)
    conn.commit()
    return root_id


def ensure_protection_policy(conn: sqlite3.Connection, root_id: int, profile: str) -> int:
    row = conn.execute(
        "SELECT id FROM protection_policies WHERE root_id = ?", (root_id,)
    ).fetchone()
    if row:
        return int(row["id"])
    now = utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO protection_policies(
            root_id, enabled, profile, auto_snapshot, watch_enabled,
            hourly_snapshot, daily_snapshot, created_at, updated_at, paused_until
        )
        VALUES (?, 1, ?, 1, 1, 1, 1, ?, ?, NULL)
        """,
        (root_id, profile, now, now),
    )
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


def set_protection_policy_enabled(
    conn: sqlite3.Connection, root_id: int, *, enabled: bool
) -> None:
    ensure_protection_policy(conn, root_id, "coding")
    conn.execute(
        """
        UPDATE protection_policies
        SET enabled = ?, watch_enabled = ?, updated_at = ?, paused_until = NULL
        WHERE root_id = ?
        """,
        (1 if enabled else 0, 1 if enabled else 0, utc_now_iso(), root_id),
    )


def list_protection_policies(conn: sqlite3.Connection) -> list[ProtectionPolicy]:
    rows = conn.execute(
        """
        SELECT
            p.id AS policy_id,
            r.id AS root_id,
            r.path AS root_path,
            p.enabled,
            p.profile,
            p.auto_snapshot,
            p.watch_enabled,
            p.hourly_snapshot,
            p.daily_snapshot,
            p.created_at,
            p.updated_at,
            p.paused_until
        FROM roots r
        JOIN protection_policies p ON p.root_id = r.id
        ORDER BY r.path
        """
    ).fetchall()
    return [policy for row in rows if (policy := _policy_from_row(row)) is not None]


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
