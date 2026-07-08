from __future__ import annotations

from datetime import UTC, datetime

from safevault.cli import app
from safevault.daemon import run_scheduled_tasks
from safevault.db import connect
from safevault.protection import add_protected_root, list_enabled_policies


def test_scheduled_snapshots_do_not_repeat_inside_interval(runner, sv_home, project) -> None:
    (project / "hourly.txt").write_text("tracked", encoding="utf-8")
    add_protected_root(project, "coding")
    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)

    run_scheduled_tasks(now=now)
    run_scheduled_tasks(now=now)

    conn = connect()
    try:
        hourly_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE reason = 'scheduled-hourly'"
            ).fetchone()[0]
        )
        daily_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE reason = 'scheduled-daily'"
            ).fetchone()[0]
        )
        batch_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM change_batches WHERE reason LIKE 'scheduled-%'"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    assert hourly_count == 1
    assert daily_count == 1
    assert batch_count == 2


def test_bulk_delete_warning_writes_notification(runner, sv_home, project) -> None:
    add_protected_root(project, "coding")
    result = runner.invoke(app, ["daemon", "run", "--test-once"])
    assert result.exit_code == 0

    from safevault.daemon import _record_bulk_delete_warning

    _record_bulk_delete_warning("bulk delete test")

    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM notifications WHERE kind = 'bulk-delete'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["severity"] == "warning"


def test_protect_pause_and_resume_affects_enabled_policies(runner, sv_home, project) -> None:
    add_protected_root(project, "coding")
    assert len(list_enabled_policies()) == 1

    pause = runner.invoke(app, ["protect", "pause", str(project), "--duration", "30m"])
    assert pause.exit_code == 0
    assert list_enabled_policies() == []

    resume = runner.invoke(app, ["protect", "resume", str(project)])
    assert resume.exit_code == 0
    assert len(list_enabled_policies()) == 1
