from __future__ import annotations

import json
import os

import pytest

from safevault.cli import app
from safevault.daemon import (
    get_daemon_lock_path,
    record_deleted_marker,
    run_daemon,
)
from safevault.db import connect
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


def test_daemon_status_json_reports_protected_roots(runner, sv_home, project) -> None:
    add_protected_root(project, "coding")

    result = runner.invoke(app, ["daemon", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] in {"stopped", "running"}
    assert data["protected_roots"] == 1


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
