from __future__ import annotations

import os
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from watchdog.observers import Observer

from safevault.backup import run_due_backup
from safevault.config import load_config
from safevault.db import connect, utc_now_iso
from safevault.errors import SafeVaultError
from safevault.paths import ensure_home_layout, get_safevault_home
from safevault.protection import list_enabled_policies
from safevault.snapshot import create_snapshot, relative_path
from safevault.verify import run_verify
from safevault.watcher import SafeVaultEventHandler

DaemonStatusValue = Literal["running", "stopped", "stopping", "error"]


@dataclass(frozen=True)
class DaemonStatus:
    status: str
    pid: int | None
    started_at: str | None
    last_heartbeat_at: str | None
    message: str | None
    lock_exists: bool
    stop_requested: bool
    protected_roots: int


class DaemonLock:
    def __init__(self) -> None:
        self.path = get_daemon_lock_path()
        self.acquired = False

    def __enter__(self) -> DaemonLock:
        ensure_home_layout()
        if self.path.exists():
            pid = _read_pid(self.path)
            if pid is not None and _process_exists(pid):
                raise SafeVaultError(f"safevault daemon is already running with pid {pid}")
            with suppress(OSError):
                self.path.unlink()
        try:
            fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise SafeVaultError("safevault daemon lock already exists") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            file_obj.write(str(os.getpid()))
            file_obj.flush()
            os.fsync(file_obj.fileno())
        self.acquired = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.acquired:
            with suppress(OSError):
                self.path.unlink()


def get_daemon_lock_path() -> Path:
    return get_safevault_home() / "daemon.lock"


def get_daemon_stop_path() -> Path:
    return get_safevault_home() / "daemon.stop"


def get_daemon_status() -> DaemonStatus:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
        roots = len(list_enabled_policies())
    finally:
        conn.close()
    if row is None:
        return DaemonStatus(
            status="stopped",
            pid=None,
            started_at=None,
            last_heartbeat_at=None,
            message=None,
            lock_exists=get_daemon_lock_path().exists(),
            stop_requested=get_daemon_stop_path().exists(),
            protected_roots=roots,
        )
    return DaemonStatus(
        status=str(row["status"]),
        pid=None if row["pid"] is None else int(row["pid"]),
        started_at=None if row["started_at"] is None else str(row["started_at"]),
        last_heartbeat_at=(
            None if row["last_heartbeat_at"] is None else str(row["last_heartbeat_at"])
        ),
        message=None if row["message"] is None else str(row["message"]),
        lock_exists=get_daemon_lock_path().exists(),
        stop_requested=get_daemon_stop_path().exists(),
        protected_roots=roots,
    )


def request_daemon_stop() -> None:
    ensure_home_layout()
    get_daemon_stop_path().write_text(utc_now_iso(), encoding="utf-8")
    _write_daemon_state(status="stopping", message="stop requested")


def run_daemon(*, test_once: bool = False, poll_interval_seconds: float = 1.0) -> None:
    config = load_config()
    ensure_home_layout()
    with DaemonLock():
        with suppress(OSError):
            get_daemon_stop_path().unlink()
        _record_crash_recovery_if_needed(config.daemon.heartbeat_interval_seconds)
        _write_daemon_state(status="running", message="starting")
        try:
            _run_startup_scan()
            _update_heartbeat("startup scan complete")
            if test_once:
                return
            _run_watch_loop(poll_interval_seconds=poll_interval_seconds)
        except Exception as exc:
            _write_daemon_state(status="error", message=str(exc))
            raise
        finally:
            _write_daemon_state(status="stopped", message="stopped")
            with suppress(OSError):
                get_daemon_stop_path().unlink()


def record_deleted_marker(root_path: Path, deleted_path: Path, *, source: str = "daemon") -> bool:
    root = root_path.expanduser().resolve(strict=False)
    path = deleted_path.expanduser().resolve(strict=False)
    try:
        rel_path = relative_path(root, path)
    except ValueError:
        return False
    conn = connect()
    try:
        file_row = conn.execute(
            """
            SELECT f.*, r.id AS root_id
            FROM files f
            JOIN roots r ON r.id = f.root_id
            WHERE r.path = ? AND f.rel_path = ? AND f.status = 'active'
            """,
            (str(root), rel_path),
        ).fetchone()
        if file_row is None:
            return False
        now = utc_now_iso()
        cur = conn.execute(
            """
            INSERT INTO snapshots(root_id, reason, label, started_at, finished_at, status)
            VALUES (?, 'watcher-delete', NULL, ?, ?, 'complete')
            """,
            (int(file_row["root_id"]), now, now),
        )
        assert cur.lastrowid is not None
        snapshot_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE files SET status = 'deleted', last_seen_at = ? WHERE id = ?",
            (now, int(file_row["id"])),
        )
        conn.execute(
            """
            INSERT INTO versions(
                file_id, snapshot_id, rel_path, content_hash, size, mtime_ns, mode,
                captured_at, is_deleted_marker
            )
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, 1)
            """,
            (
                int(file_row["id"]),
                snapshot_id,
                rel_path,
                file_row["size"],
                file_row["mtime_ns"],
                file_row["mode"],
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO events(root_id, event_type, rel_path, old_rel_path, detected_at, source)
            VALUES (?, 'deleted', ?, NULL, ?, ?)
            """,
            (int(file_row["root_id"]), rel_path, now, source),
        )
        record_notification(
            conn,
            kind="delete",
            severity="info",
            title="Deleted file recorded",
            message=rel_path,
        )
        _insert_change_batch(
            conn,
            root_id=int(file_row["root_id"]),
            reason="watcher-delete",
            status="complete",
            deleted_count=1,
            snapshot_id=snapshot_id,
        )
        conn.commit()
        return True
    finally:
        conn.close()


def record_notification(
    conn,
    *,
    kind: str,
    severity: str,
    title: str,
    message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO notifications(kind, severity, title, message, created_at, read_at)
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (kind, severity, title, message, utc_now_iso()),
    )


def _create_batched_snapshot(root_path: Path, reason: str) -> int:
    snapshot_id = create_snapshot(root_path, reason=reason)
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id FROM roots WHERE path = ?",
            (str(root_path.expanduser().resolve(strict=False)),),
        ).fetchone()
        if row is not None:
            _insert_change_batch(
                conn,
                root_id=int(row["id"]),
                reason=reason,
                status="complete",
                snapshot_id=snapshot_id,
            )
            conn.commit()
    finally:
        conn.close()
    return snapshot_id


def _insert_change_batch(
    conn,
    *,
    root_id: int,
    reason: str,
    status: str,
    created_count: int = 0,
    modified_count: int = 0,
    deleted_count: int = 0,
    snapshot_id: int | None = None,
) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO change_batches(
            id, root_id, started_at, last_event_at, reason, status,
            created_count, modified_count, deleted_count, snapshot_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            root_id,
            now,
            now,
            reason,
            status,
            created_count,
            modified_count,
            deleted_count,
            snapshot_id,
        ),
    )


def run_scheduled_tasks(*, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    _run_due_snapshots(current)
    run_due_backup(now=current)
    _run_idle_verify(current)


def _run_watch_loop(*, poll_interval_seconds: float) -> None:
    config = load_config()
    policies = list_enabled_policies()
    observer = Observer()
    handlers: list[SafeVaultEventHandler] = []
    for policy in policies:
        root_path = Path(policy.root_path)
        if not root_path.is_dir():
            _create_notification(
                kind="root",
                severity="warning",
                title="Protected root unavailable",
                message=policy.root_path,
            )
            continue
        handler = SafeVaultEventHandler(
            root_path,
            snapshot_func=lambda path, reason: _create_batched_snapshot(
                path,
                "watcher-change" if reason == "watch" else reason,
            ),
            debounce_seconds=float(config.daemon.watch_debounce_seconds),
            warn_func=_record_bulk_delete_warning,
            deleted_func=_record_deleted_from_watcher,
            bulk_delete_threshold=config.daemon.bulk_delete_threshold,
            bulk_delete_window_seconds=float(config.daemon.bulk_delete_window_seconds),
        )
        handlers.append(handler)
        observer.schedule(handler, str(root_path), recursive=True)
    observer.start()
    try:
        while not get_daemon_stop_path().exists():
            _update_heartbeat("running")
            run_scheduled_tasks()
            time.sleep(poll_interval_seconds)
    finally:
        for handler in handlers:
            handler.stop()
        observer.stop()
        observer.join()


def _run_startup_scan() -> None:
    for policy in list_enabled_policies():
        root_path = Path(policy.root_path)
        if root_path.is_dir():
            _create_batched_snapshot(root_path, "pre-daemon-start")


def _record_deleted_from_watcher(root: Path, path: Path) -> None:
    record_deleted_marker(root, path)


def _run_due_snapshots(now: datetime) -> None:
    config = load_config()
    conn = connect()
    try:
        policies = list_enabled_policies()
        for policy in policies:
            if config.daemon.hourly_snapshot_enabled and policy.hourly_snapshot:
                _run_due_snapshot_for_policy(
                    conn,
                    policy.root_id,
                    Path(policy.root_path),
                    "scheduled-hourly",
                    now,
                    timedelta(hours=1),
                )
            if config.daemon.daily_snapshot_enabled and policy.daily_snapshot:
                _run_due_snapshot_for_policy(
                    conn,
                    policy.root_id,
                    Path(policy.root_path),
                    "scheduled-daily",
                    now,
                    timedelta(days=1),
                )
    finally:
        conn.close()


def _run_due_snapshot_for_policy(
    conn,
    root_id: int,
    root_path: Path,
    reason: str,
    now: datetime,
    interval: timedelta,
) -> None:
    if not root_path.is_dir():
        return
    row = conn.execute(
        """
        SELECT started_at
        FROM snapshots
        WHERE root_id = ? AND reason = ? AND status = 'complete'
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """,
        (root_id, reason),
    ).fetchone()
    if row is not None and now - _parse_iso(str(row["started_at"])) < interval:
        return
    _create_batched_snapshot(root_path, reason)


def _run_idle_verify(now: datetime) -> None:
    config = load_config()
    if not config.daemon.idle_verify_enabled:
        return
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT detected_at
            FROM events
            ORDER BY detected_at DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        idle_for = now - _parse_iso(str(row["detected_at"]))
        if idle_for < timedelta(minutes=config.daemon.idle_verify_after_minutes):
            return
    result = run_verify(deep=False)
    if not result.healthy:
        _create_notification(
            kind="verify",
            severity="error",
            title="SafeVault verify failed",
            message="missing or corrupted referenced objects were found",
        )


def _write_daemon_state(
    *,
    status: DaemonStatusValue,
    message: str | None = None,
) -> None:
    now = utc_now_iso()
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO daemon_state(
                id, pid, status, started_at, last_heartbeat_at, message
            )
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                pid = excluded.pid,
                status = excluded.status,
                started_at = COALESCE(daemon_state.started_at, excluded.started_at),
                last_heartbeat_at = excluded.last_heartbeat_at,
                message = excluded.message
            """,
            (os.getpid(), status, now, now, message),
        )
        conn.commit()
    finally:
        conn.close()


def _update_heartbeat(message: str | None = None) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO daemon_state(
                id, pid, status, started_at, last_heartbeat_at, message
            )
            VALUES (1, ?, 'running', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                pid = excluded.pid,
                status = 'running',
                last_heartbeat_at = excluded.last_heartbeat_at,
                message = excluded.message
            """,
            (os.getpid(), utc_now_iso(), utc_now_iso(), message),
        )
        conn.commit()
    finally:
        conn.close()


def _record_crash_recovery_if_needed(heartbeat_interval_seconds: int) -> None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
        if row is None or str(row["status"]) != "running":
            return
        heartbeat = row["last_heartbeat_at"]
        if heartbeat is None:
            stale = True
        else:
            stale = datetime.now(UTC) - _parse_iso(str(heartbeat)) > timedelta(
                seconds=heartbeat_interval_seconds * 3
            )
        if stale:
            record_notification(
                conn,
                kind="daemon",
                severity="warning",
                title="SafeVault daemon restarted",
                message="previous daemon heartbeat was stale",
            )
            conn.commit()
    finally:
        conn.close()


def _record_bulk_delete_warning(message: str) -> None:
    _create_notification(
        kind="bulk-delete",
        severity="warning",
        title="Bulk delete activity detected",
        message=message,
    )


def _create_notification(*, kind: str, severity: str, title: str, message: str) -> None:
    conn = connect()
    try:
        record_notification(
            conn,
            kind=kind,
            severity=severity,
            title=title,
            message=message,
        )
        conn.commit()
    finally:
        conn.close()


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
