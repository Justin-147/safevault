from __future__ import annotations

import json
import os

import pytest

import safevault.daemon as daemon_module
from safevault.cli import app
from safevault.daemon import (
    DaemonPolicyRegistry,
    get_daemon_lock_path,
    record_deleted_marker,
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

    def schedule(self, handler, path: str, recursive: bool):
        watch = (path, len(self.scheduled), recursive)
        self.scheduled.append((handler, path, recursive, watch))
        return watch

    def unschedule(self, watch) -> None:
        self.unscheduled.append(watch)


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
