from __future__ import annotations

import ctypes
import os
import sqlite3
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from watchdog.observers import Observer

from safevault.backup import run_due_backup
from safevault.config import DaemonConfig, load_config
from safevault.db import (
    connect,
    insert_file_event,
    insert_restore_point,
    insert_version_timeline,
    utc_now_iso,
)
from safevault.errors import SafeVaultError
from safevault.models import ProtectionPolicy
from safevault.paths import ensure_home_layout, get_safevault_home
from safevault.protection import (
    list_enabled_policies,
    list_protection,
    policy_is_watchable,
    root_safety_issue,
)
from safevault.retention_cleanup import run_due_retention_cleanup
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
    watched_roots: int
    paused_roots: int
    missing_roots: int


@dataclass(frozen=True)
class DaemonPolicyCounts:
    protected_roots: int
    watched_roots: int
    paused_roots: int
    missing_roots: int


@dataclass
class WatchedRoot:
    root_id: int
    root_path: Path
    handler: SafeVaultEventHandler
    watch: object


class DaemonPolicyRegistry:
    def __init__(self, observer, *, auto_flush: bool = True) -> None:
        self.observer = observer
        self.watched: dict[int, WatchedRoot] = {}
        self.auto_flush = auto_flush

    def sync(
        self,
        policies: list[ProtectionPolicy],
        config: DaemonConfig,
        *,
        now: datetime | None = None,
        snapshot_new: bool = False,
    ) -> None:
        current = datetime.now(UTC) if now is None else now
        target: dict[int, ProtectionPolicy] = {}
        for policy in policies:
            root_path = Path(policy.root_path)
            if policy.enabled and not root_path.exists():
                self.unschedule(policy.root_id)
                _create_notification(
                    kind="root",
                    severity="warning",
                    title="Protected root unavailable",
                    message=policy.root_path,
                )
                continue
            issue = root_safety_issue(root_path)
            if policy.enabled and issue is not None:
                self.unschedule(policy.root_id)
                _create_notification(
                    kind="root",
                    severity="warning",
                    title="Unsafe protected root skipped",
                    message=f"{policy.root_path}: {issue}",
                )
                continue
            if not policy_is_watchable(policy, current):
                self.unschedule(policy.root_id)
                continue
            target[policy.root_id] = policy

        for root_id in list(self.watched):
            watched = self.watched[root_id]
            target_policy = target.get(root_id)
            if target_policy is None or Path(target_policy.root_path) != watched.root_path:
                self.unschedule(root_id)

        for root_id, policy in target.items():
            if root_id in self.watched:
                continue
            self.schedule(policy, config)
            if snapshot_new:
                _create_batched_snapshot(Path(policy.root_path), "daemon-policy-add")

    def schedule(self, policy: ProtectionPolicy, config: DaemonConfig) -> None:
        root_path = Path(policy.root_path)
        handler = SafeVaultEventHandler(
            root_path,
            snapshot_func=lambda path, reason: _create_batched_snapshot(
                path,
                "watcher-change" if reason == "watch" else reason,
            ),
            debounce_seconds=float(config.watch_debounce_seconds),
            warn_func=_record_high_risk_warning,
            deleted_func=_record_deleted_from_watcher,
            moved_func=_record_moved_from_watcher,
            bulk_delete_threshold=config.bulk_delete_threshold,
            bulk_delete_window_seconds=float(config.bulk_delete_window_seconds),
            auto_flush=self.auto_flush,
        )
        watch = self.observer.schedule(handler, str(root_path), recursive=True)
        self.watched[policy.root_id] = WatchedRoot(
            root_id=policy.root_id,
            root_path=root_path,
            handler=handler,
            watch=watch,
        )

    def unschedule(self, root_id: int) -> None:
        watched = self.watched.pop(root_id, None)
        if watched is None:
            return
        watched.handler.stop()
        self.observer.unschedule(watched.watch)

    def stop_all(self) -> None:
        for root_id in list(self.watched):
            self.unschedule(root_id)

    def enable_auto_flush(self) -> None:
        self.auto_flush = True
        for watched in self.watched.values():
            watched.handler.enable_auto_flush()


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
    counts = _daemon_policy_counts()
    lock_path = get_daemon_lock_path()
    lock_exists = lock_path.exists()
    lock_pid = _read_pid(lock_path) if lock_exists else None
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
    finally:
        conn.close()
    if row is None:
        return DaemonStatus(
            status="stopped",
            pid=None,
            started_at=None,
            last_heartbeat_at=None,
            message=None,
            lock_exists=lock_exists,
            stop_requested=get_daemon_stop_path().exists(),
            protected_roots=counts.protected_roots,
            watched_roots=counts.watched_roots,
            paused_roots=counts.paused_roots,
            missing_roots=counts.missing_roots,
        )
    stored_status = str(row["status"])
    stored_pid = None if row["pid"] is None else int(row["pid"])
    runtime_alive = (
        lock_pid is not None
        and stored_pid == lock_pid
        and _process_exists(lock_pid)
    )
    status = stored_status
    message = None if row["message"] is None else str(row["message"])
    pid = stored_pid
    if stored_status == "running" and not runtime_alive:
        status = "error"
        pid = None
        message = "background process is not running; restart SafeVault"
    elif stored_status == "stopping" and not runtime_alive:
        status = "stopped"
        pid = None
        message = "stopped"
    return DaemonStatus(
        status=status,
        pid=pid,
        started_at=None if row["started_at"] is None else str(row["started_at"]),
        last_heartbeat_at=(
            None if row["last_heartbeat_at"] is None else str(row["last_heartbeat_at"])
        ),
        message=message,
        lock_exists=lock_exists,
        stop_requested=get_daemon_stop_path().exists(),
        protected_roots=counts.protected_roots,
        watched_roots=counts.watched_roots,
        paused_roots=counts.paused_roots,
        missing_roots=counts.missing_roots,
    )


def _daemon_policy_counts(now: datetime | None = None) -> DaemonPolicyCounts:
    current = datetime.now(UTC) if now is None else now
    protected = 0
    watched = 0
    paused = 0
    missing = 0
    for policy in list_protection():
        if not policy.enabled:
            continue
        protected += 1
        root_path = Path(policy.root_path)
        if not root_path.exists():
            missing += 1
            continue
        if _policy_is_paused(policy, current):
            paused += 1
            continue
        if policy_is_watchable(policy, current):
            watched += 1
    return DaemonPolicyCounts(
        protected_roots=protected,
        watched_roots=watched,
        paused_roots=paused,
        missing_roots=missing,
    )


def _policy_is_paused(policy: ProtectionPolicy, now: datetime) -> bool:
    return policy.paused_until is not None and _parse_iso(policy.paused_until) > now


def request_daemon_stop() -> None:
    ensure_home_layout()
    lock_path = get_daemon_lock_path()
    lock_pid = _read_pid(lock_path)
    if lock_pid is None or not _process_exists(lock_pid):
        with suppress(OSError):
            lock_path.unlink()
        with suppress(OSError):
            get_daemon_stop_path().unlink()
        _write_daemon_state(status="stopped", message="already stopped")
        return
    get_daemon_stop_path().write_text(utc_now_iso(), encoding="utf-8")
    _write_daemon_state(status="stopping", message="stop requested")


def run_daemon(
    *,
    test_once: bool = False,
    poll_interval_seconds: float = 1.0,
    force: bool = False,
) -> None:
    config = load_config()
    if not config.daemon.enabled and not force:
        raise SafeVaultError("daemon is disabled in config; pass --force to run anyway")
    ensure_home_layout()
    with DaemonLock():
        with suppress(OSError):
            get_daemon_stop_path().unlink()
        _record_crash_recovery_if_needed(config.daemon.heartbeat_interval_seconds)
        _write_daemon_state(status="running", message="starting", reset_started=True)
        had_error = False
        try:
            if test_once:
                _run_startup_scan()
                _update_heartbeat("startup scan complete")
                return
            _run_watch_loop(poll_interval_seconds=poll_interval_seconds)
        except Exception as exc:
            had_error = True
            _write_daemon_state(status="error", message=str(exc))
            raise
        finally:
            if not had_error:
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
        file_id = int(file_row["id"])
        conn.execute(
            "UPDATE files SET status = 'deleted', last_seen_at = ? WHERE id = ?",
            (now, file_id),
        )
        version_cur = conn.execute(
            """
            INSERT INTO versions(
                file_id, snapshot_id, rel_path, content_hash, size, mtime_ns, mode,
                captured_at, is_deleted_marker
            )
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, 1)
            """,
            (
                file_id,
                snapshot_id,
                rel_path,
                file_row["size"],
                file_row["mtime_ns"],
                file_row["mode"],
                now,
            ),
        )
        assert version_cur.lastrowid is not None
        insert_version_timeline(
            conn,
            root_id=int(file_row["root_id"]),
            file_id=file_id,
            version_id=int(version_cur.lastrowid),
            snapshot_id=snapshot_id,
            rel_path=rel_path,
            event_type="deleted",
            occurred_at=now,
        )
        conn.execute(
            """
            INSERT INTO events(root_id, event_type, rel_path, old_rel_path, detected_at, source)
            VALUES (?, 'deleted', ?, NULL, ?, ?)
            """,
            (int(file_row["root_id"]), rel_path, now, source),
        )
        insert_file_event(
            conn,
            root_id=int(file_row["root_id"]),
            file_id=file_id,
            snapshot_id=snapshot_id,
            event_type="deleted",
            rel_path=rel_path,
            detected_at=now,
            source=source,
        )
        insert_restore_point(
            conn,
            root_id=int(file_row["root_id"]),
            snapshot_id=snapshot_id,
            reason="watcher-delete",
            created_at=now,
            source=source,
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
    run_due_retention_cleanup(now=current)
    _run_idle_verify(current)


def _run_watch_loop(*, poll_interval_seconds: float) -> None:
    config = load_config()
    observer = Observer()
    registry = DaemonPolicyRegistry(observer, auto_flush=False)
    registry.sync(list_protection(), config.daemon)
    observer.start()
    try:
        # Watch first so changes to an already-scanned root cannot be missed while
        # startup reconciliation continues through other, potentially large roots.
        _run_startup_scan()
        _update_heartbeat("startup scan complete")
        registry.enable_auto_flush()
        last_policy_refresh = time.monotonic()
        while not get_daemon_stop_path().exists():
            _update_heartbeat("running")
            now = time.monotonic()
            if now - last_policy_refresh >= config.daemon.policy_refresh_seconds:
                config = load_config()
                registry.sync(list_protection(), config.daemon, snapshot_new=True)
                last_policy_refresh = now
            run_scheduled_tasks()
            time.sleep(poll_interval_seconds)
    finally:
        registry.stop_all()
        observer.stop()
        observer.join()


def _run_startup_scan() -> None:
    _notify_skipped_unsafe_roots()
    for policy in list_enabled_policies():
        root_path = Path(policy.root_path)
        if root_path.is_dir():
            _create_batched_snapshot(root_path, "pre-daemon-start")


def _notify_skipped_unsafe_roots() -> None:
    for policy in list_protection():
        issue = root_safety_issue(Path(policy.root_path))
        if issue is not None:
            _create_notification(
                kind="root",
                severity="warning",
                title="Unsafe protected root skipped",
                message=f"{policy.root_path}: {issue}",
            )


def _record_deleted_from_watcher(root: Path, path: Path) -> None:
    for attempt in range(2):
        try:
            record_deleted_marker(root, path)
            return
        except sqlite3.OperationalError as exc:
            message = str(exc).casefold()
            if "locked" not in message and "busy" not in message:
                raise
            if attempt == 0:
                time.sleep(0.2)
    # A scheduled snapshot will reconcile the deletion later. Most importantly,
    # a temporary database lock must not terminate watchdog's observer thread.


def _record_moved_from_watcher(root: Path, src: Path, dest: Path) -> None:
    record_moved_event(root, src, dest)


def record_moved_event(root_path: Path, src_path: Path, dest_path: Path) -> bool:
    root = root_path.expanduser().resolve(strict=False)
    try:
        old_rel = relative_path(root, src_path.expanduser().resolve(strict=False))
        new_rel = relative_path(root, dest_path.expanduser().resolve(strict=False))
    except ValueError:
        return False
    conn = connect()
    try:
        row = conn.execute("SELECT id FROM roots WHERE path = ?", (str(root),)).fetchone()
        if row is None:
            return False
        root_id = int(row["id"])
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO events(root_id, event_type, rel_path, old_rel_path, detected_at, source)
            VALUES (?, 'moved', ?, ?, ?, 'daemon')
            """,
            (root_id, new_rel, old_rel, now),
        )
        insert_file_event(
            conn,
            root_id=root_id,
            event_type="moved",
            rel_path=new_rel,
            old_rel_path=old_rel,
            detected_at=now,
            source="daemon",
        )
        conn.commit()
        return True
    finally:
        conn.close()


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
    reset_started: bool = False,
) -> None:
    now = utc_now_iso()
    stopped_at = now if status in {"stopped", "error"} else None
    pid = os.getpid() if status == "running" else None
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO daemon_state(
                id, pid, status, started_at, last_heartbeat_at, message, stopped_at
            )
            VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                pid = CASE
                    WHEN excluded.status = 'stopping' THEN daemon_state.pid
                    ELSE excluded.pid
                END,
                status = excluded.status,
                started_at = CASE
                    WHEN ? THEN excluded.started_at
                    ELSE COALESCE(daemon_state.started_at, excluded.started_at)
                END,
                last_heartbeat_at = excluded.last_heartbeat_at,
                message = excluded.message,
                stopped_at = excluded.stopped_at
            """,
            (
                pid,
                status,
                now,
                now,
                message,
                stopped_at,
                1 if reset_started else 0,
            ),
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


def _record_high_risk_warning(message: str) -> None:
    is_delete = "delete" in message.lower()
    is_emergency = "emergency" in message.lower()
    _create_notification(
        kind=(
            "bulk-delete"
            if is_delete
            else "mass-change"
            if is_emergency
            else "large-change"
        ),
        severity="error" if is_emergency else "warning",
        title=(
            "Bulk delete activity detected"
            if is_delete
            else "Emergency mass change detected"
            if is_emergency
            else "Large file change detected"
        ),
        message=message,
    )


def _record_bulk_delete_warning(message: str) -> None:
    _record_high_risk_warning(message)


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
    if os.name == "nt":
        return _windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_process_exists(pid: int) -> bool:
    win_dll = getattr(ctypes, "WinDLL", None)
    get_last_error = getattr(ctypes, "get_last_error", None)
    if win_dll is None or get_last_error is None:
        return False

    kernel32 = win_dll("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    open_process.restype = ctypes.c_void_p
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    get_exit_code.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    handle = open_process(process_query_limited_information, False, pid)
    if not handle:
        return int(get_last_error()) == error_access_denied
    try:
        exit_code = ctypes.c_ulong()
        if not get_exit_code(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        close_handle(handle)


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
