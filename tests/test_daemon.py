from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import safevault.daemon as daemon_module
from safevault.cli import app
from safevault.config import DaemonConfig, SafeVaultConfig, save_config
from safevault.daemon import (
    DaemonPolicyRegistry,
    get_daemon_lock_path,
    get_daemon_status,
    record_deleted_marker,
    request_daemon_stop,
    run_daemon,
)
from safevault.db import connect, get_or_create_root
from safevault.errors import SafeVaultError
from safevault.protection import add_protected_root
from safevault.snapshot import create_snapshot


def test_daemon_test_once_runs_startup_scan_and_updates_state(runner, sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    add_protected_root(project, "coding")

    result = runner.invoke(app, ["daemon", "run", "--test-once"])

    assert result.exit_code == 0
    conn = connect()
    try:
        snapshot = conn.execute(
            "SELECT * FROM snapshots WHERE reason = 'pre-daemon-start'"
        ).fetchone()
        state = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
    finally:
        conn.close()
    assert snapshot is not None
    assert state is not None
    assert state["status"] == "stopped"
    assert state["pid"] is None
    assert state["last_heartbeat_at"] is not None
    assert state["stopped_at"] is not None


def test_daemon_status_json_reports_protected_roots(runner, sv_home, project) -> None:
    add_protected_root(project, "coding")

    result = runner.invoke(app, ["daemon", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] in {"stopped", "running"}
    assert data["protected_roots"] == 1
    assert data["watched_roots"] == 1
    assert data["paused_roots"] == 0
    assert data["missing_roots"] == 0


def test_daemon_status_json_includes_watched_paused_missing_counts(
    runner, sv_home, project, tmp_path
) -> None:
    paused_root = tmp_path / "paused-root"
    missing_root = tmp_path / "missing-root"
    paused_root.mkdir()
    missing_root.mkdir()
    add_protected_root(project, "coding")
    add_protected_root(paused_root, "coding")
    add_protected_root(missing_root, "coding")
    assert (
        runner.invoke(app, ["protect", "pause", str(paused_root), "--duration", "30m"]).exit_code
        == 0
    )
    missing_root.rmdir()

    result = runner.invoke(app, ["daemon", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["protected_roots"] == 3
    assert data["watched_roots"] == 1
    assert data["paused_roots"] == 1
    assert data["missing_roots"] == 1


def test_daemon_single_instance_lock_rejects_running_process(sv_home) -> None:
    sv_home.mkdir(parents=True)
    get_daemon_lock_path().write_text(str(os.getpid()), encoding="utf-8")

    with pytest.raises(SafeVaultError, match="already running"):
        run_daemon(test_once=True)


def test_record_deleted_marker_marks_tracked_file_deleted(sv_home, project) -> None:
    target = project / "gone.txt"
    target.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target.unlink()

    assert record_deleted_marker(project, target) is True

    conn = connect()
    try:
        file_row = conn.execute("SELECT * FROM files WHERE rel_path = 'gone.txt'").fetchone()
        marker = conn.execute(
            "SELECT * FROM versions WHERE rel_path = 'gone.txt' AND is_deleted_marker = 1"
        ).fetchone()
        notification = conn.execute(
            "SELECT * FROM notifications WHERE kind = 'delete'"
        ).fetchone()
    finally:
        conn.close()
    assert file_row["status"] == "deleted"
    assert marker is not None
    assert notification is not None


def test_daemon_stop_creates_stop_request(runner, sv_home) -> None:
    result = runner.invoke(app, ["daemon", "stop"])

    assert result.exit_code == 0
    assert (sv_home / "daemon.stop").is_file() is False
    assert get_daemon_status().status == "stopped"


def test_daemon_status_rejects_stale_running_database_state(sv_home) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO daemon_state(
                id, pid, status, started_at, last_heartbeat_at, message
            )
            VALUES (1, 999999, 'running', '2026-07-10T00:00:00+00:00',
                    '2026-07-10T00:00:00+00:00', 'running')
            """
        )
        conn.commit()
    finally:
        conn.close()

    status = get_daemon_status()

    assert status.status == "error"
    assert status.pid is None
    assert status.lock_exists is False
    assert status.message == "background process is not running; restart SafeVault"


def test_stop_request_on_stale_daemon_settles_to_stopped(sv_home) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO daemon_state(
                id, pid, status, started_at, last_heartbeat_at, message
            )
            VALUES (1, 999999, 'running', '2026-07-10T00:00:00+00:00',
                    '2026-07-10T00:00:00+00:00', 'running')
            """
        )
        conn.commit()
    finally:
        conn.close()

    request_daemon_stop()

    assert get_daemon_status().status == "stopped"
    assert (sv_home / "daemon.stop").exists() is False


def test_stop_request_preserves_running_pid_until_daemon_exits(sv_home) -> None:
    get_daemon_lock_path().parent.mkdir(parents=True, exist_ok=True)
    get_daemon_lock_path().write_text(str(os.getpid()), encoding="utf-8")
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO daemon_state(
                id, pid, status, started_at, last_heartbeat_at, message
            )
            VALUES (1, ?, 'running', '2026-07-10T00:00:00+00:00',
                    '2026-07-10T00:00:00+00:00', 'running')
            """,
            (os.getpid(),),
        )
        conn.commit()
    finally:
        conn.close()

    request_daemon_stop()

    status = get_daemon_status()
    assert status.status == "stopping"
    assert status.pid == os.getpid()
    assert (sv_home / "daemon.stop").is_file()


def test_daemon_skips_unsafe_legacy_root_and_reports_notification(
    runner, sv_home
) -> None:
    sv_home.mkdir(parents=True)
    conn = connect()
    try:
        get_or_create_root(conn, sv_home, "coding")
    finally:
        conn.close()

    result = runner.invoke(app, ["daemon", "run", "--test-once"])

    assert result.exit_code == 0
    conn = connect()
    try:
        snapshots = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
        notification = conn.execute(
            """
            SELECT * FROM notifications
            WHERE title = 'Unsafe protected root skipped'
            """
        ).fetchone()
    finally:
        conn.close()
    assert snapshots == 0
    assert notification is not None
    assert "SAFEVAULT_HOME" in notification["message"]


def test_daemon_error_state_is_not_overwritten_by_stopped(
    sv_home, monkeypatch
) -> None:
    def fail_startup_scan() -> None:
        raise RuntimeError("startup exploded")

    monkeypatch.setattr(daemon_module, "_run_startup_scan", fail_startup_scan)

    with pytest.raises(RuntimeError, match="startup exploded"):
        run_daemon(test_once=True)

    conn = connect()
    try:
        state = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
    finally:
        conn.close()
    assert state["status"] == "error"
    assert state["message"] == "startup exploded"
    assert state["stopped_at"] is not None


def test_daemon_started_at_refreshes_on_new_run(sv_home) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO daemon_state(
                id, pid, status, started_at, last_heartbeat_at, message
            )
            VALUES (1, 123, 'stopped', '2000-01-01T00:00:00+00:00',
                    '2000-01-01T00:00:00+00:00', 'old')
            """
        )
        conn.commit()
    finally:
        conn.close()

    run_daemon(test_once=True)

    conn = connect()
    try:
        state = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
    finally:
        conn.close()
    assert state["status"] == "stopped"
    assert state["started_at"] != "2000-01-01T00:00:00+00:00"
    assert state["pid"] is None


def test_daemon_run_respects_disabled_config(runner, sv_home) -> None:
    save_config(SafeVaultConfig(daemon=DaemonConfig(enabled=False)))

    result = runner.invoke(app, ["daemon", "run", "--test-once"])

    assert result.exit_code != 0
    assert "daemon is disabled" in result.output


def test_daemon_run_force_ignores_disabled_config(runner, sv_home) -> None:
    save_config(SafeVaultConfig(daemon=DaemonConfig(enabled=False)))

    result = runner.invoke(app, ["daemon", "run", "--test-once", "--force"])

    assert result.exit_code == 0


def test_daemon_crash_recovery_notification_still_works(sv_home) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO daemon_state(
                id, pid, status, started_at, last_heartbeat_at, message
            )
            VALUES (1, 123, 'running', '2000-01-01T00:00:00+00:00',
                    '2000-01-01T00:00:00+00:00', 'old')
            """
        )
        conn.commit()
    finally:
        conn.close()

    run_daemon(test_once=True)

    conn = connect()
    try:
        notification = conn.execute(
            "SELECT * FROM notifications WHERE title = 'SafeVault daemon restarted'"
        ).fetchone()
    finally:
        conn.close()
    assert notification is not None


class FakeObserver:
    def __init__(self) -> None:
        self.scheduled = []
        self.unscheduled = []
        self.started = False
        self.stopped = False
        self.joined = False

    def schedule(self, handler, path: str, recursive: bool):
        watch = (path, len(self.scheduled), recursive)
        self.scheduled.append((handler, path, recursive, watch))
        return watch

    def unschedule(self, watch) -> None:
        self.unscheduled.append(watch)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self) -> None:
        self.joined = True


def test_process_exists_detects_another_live_process() -> None:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=creationflags,
    )
    try:
        assert daemon_module._process_exists(process.pid) is True
    finally:
        process.terminate()
        process.wait(timeout=10)
    assert daemon_module._process_exists(process.pid) is False


def test_watch_loop_starts_observer_before_startup_scan(
    sv_home, project, monkeypatch
) -> None:
    add_protected_root(project, "coding")
    observer = FakeObserver()
    scan_observer_states: list[bool] = []
    daemon_module.get_daemon_stop_path().write_text("stop", encoding="utf-8")
    monkeypatch.setattr(daemon_module, "Observer", lambda: observer)
    monkeypatch.setattr(
        daemon_module,
        "_run_startup_scan",
        lambda: scan_observer_states.append(observer.started),
    )

    daemon_module._run_watch_loop(poll_interval_seconds=0.01)

    assert scan_observer_states == [True]
    assert observer.scheduled[0][0].auto_flush is True
    assert observer.stopped is True
    assert observer.joined is True


def test_daemon_policy_registry_adds_new_root(sv_home, project) -> None:
    add_protected_root(project, "coding")
    policies = list(daemon_module.list_protection())
    observer = FakeObserver()
    registry = DaemonPolicyRegistry(observer)

    registry.sync(policies, daemon_module.load_config().daemon)

    assert len(observer.scheduled) == 1
    assert len(registry.watched) == 1


def test_daemon_policy_registry_unschedules_removed_root(sv_home, project) -> None:
    add_protected_root(project, "coding")
    policy = daemon_module.list_protection()[0]
    observer = FakeObserver()
    registry = DaemonPolicyRegistry(observer)
    registry.sync([policy], daemon_module.load_config().daemon)

    registry.sync([], daemon_module.load_config().daemon)

    assert observer.unscheduled
    assert registry.watched == {}


def test_daemon_policy_registry_unschedules_paused_root(runner, sv_home, project) -> None:
    add_protected_root(project, "coding")
    policy = daemon_module.list_protection()[0]
    observer = FakeObserver()
    registry = DaemonPolicyRegistry(observer)
    registry.sync([policy], daemon_module.load_config().daemon)
    result = runner.invoke(app, ["protect", "pause", str(project), "--duration", "30m"])
    assert result.exit_code == 0

    registry.sync(daemon_module.list_protection(), daemon_module.load_config().daemon)

    assert observer.unscheduled
    assert registry.watched == {}


def test_daemon_policy_registry_reschedules_after_pause_expiry(
    runner, sv_home, project
) -> None:
    add_protected_root(project, "coding")
    assert runner.invoke(app, ["protect", "pause", str(project), "--duration", "1m"]).exit_code == 0
    observer = FakeObserver()
    registry = DaemonPolicyRegistry(observer)

    registry.sync(
        daemon_module.list_protection(),
        daemon_module.load_config().daemon,
        now=daemon_module.datetime.now(daemon_module.UTC) + daemon_module.timedelta(minutes=2),
    )

    assert len(observer.scheduled) == 1


def test_daemon_policy_registry_records_missing_root_notification(
    sv_home, project
) -> None:
    add_protected_root(project, "coding")
    policy = daemon_module.list_protection()[0]
    project.rmdir()
    observer = FakeObserver()
    registry = DaemonPolicyRegistry(observer)

    registry.sync([policy], daemon_module.load_config().daemon)

    conn = connect()
    try:
        notification = conn.execute(
            "SELECT * FROM notifications WHERE title = 'Protected root unavailable'"
        ).fetchone()
    finally:
        conn.close()
    assert notification is not None
