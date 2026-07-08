from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from safevault.backup import get_backup_status, next_due_after, run_due_backup
from safevault.cli import app
from safevault.db import connect, utc_now_iso
from safevault.snapshot import create_snapshot


def test_backup_configure_run_status_and_disable(
    runner, sv_home, project, tmp_path: Path
) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target = tmp_path / "backups"

    configured = runner.invoke(
        app,
        [
            "backup",
            "configure",
            "--target",
            str(target),
            "--schedule",
            "daily",
            "--time",
            "00:00",
            "--json",
        ],
    )
    assert configured.exit_code == 0
    assert json.loads(configured.output)["enabled"] is True
    assert json.loads(configured.output)["time"] == "00:00"

    result = runner.invoke(app, ["backup", "run", "--json"])
    assert result.exit_code == 0
    output = Path(json.loads(result.output)["output"])
    assert output.is_file()
    assert (target / "safevault-latest.tar.gz").is_file()

    status = runner.invoke(app, ["backup", "status", "--json"])
    assert status.exit_code == 0
    assert json.loads(status.output)["last_success_at"] is not None
    assert json.loads(status.output)["next_due_at"] is not None

    disabled = runner.invoke(app, ["backup", "disable", "--json"])
    assert disabled.exit_code == 0
    assert json.loads(disabled.output)["enabled"] is False


def test_backup_configure_rejects_target_inside_protected_root(
    runner, sv_home, project
) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target = project / "backups"

    result = runner.invoke(app, ["backup", "configure", "--target", str(target)])

    assert result.exit_code != 0
    assert "protected root" in result.output


def test_backup_configure_does_not_create_rejected_target_inside_safevault_home(
    runner, sv_home
) -> None:
    target = sv_home / "nested" / "backup"

    result = runner.invoke(app, ["backup", "configure", "--target", str(target)])

    assert result.exit_code != 0
    assert not target.exists()


def test_backup_configure_does_not_create_rejected_target_inside_protected_root(
    runner, sv_home, project
) -> None:
    create_snapshot(project)
    target = project / "nested" / "backup"

    result = runner.invoke(app, ["backup", "configure", "--target", str(target)])

    assert result.exit_code != 0
    assert not target.exists()


def test_due_backup_runs_after_interval(runner, sv_home, project, tmp_path: Path) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target = tmp_path / "scheduled-backups"
    assert (
        runner.invoke(
            app,
            ["backup", "configure", "--target", str(target), "--time", "00:00"],
        ).exit_code
        == 0
    )

    assert run_due_backup(now=datetime.now(UTC)) is True
    assert get_backup_status().last_success_at is not None
    assert run_due_backup(now=datetime.now(UTC)) is False


def test_due_backup_runs_when_last_success_is_old(
    runner, sv_home, project, tmp_path: Path
) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target = tmp_path / "old-backups"
    assert (
        runner.invoke(
            app,
            ["backup", "configure", "--target", str(target), "--time", "00:00"],
        ).exit_code
        == 0
    )
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat(timespec="microseconds")
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO backup_jobs(
                started_at, finished_at, status, target_path, archive_path, object_count
            )
            VALUES (?, ?, 'success', ?, ?, 0)
            """,
            (old, old, str(target), str(target / "old.tar.gz")),
        )
        conn.commit()
    finally:
        conn.close()

    assert run_due_backup(now=datetime.now(UTC)) is True


def test_backup_job_records_failure(runner, sv_home, tmp_path: Path) -> None:
    target = tmp_path / "failure-backups"
    assert (
        runner.invoke(app, ["backup", "configure", "--target", str(target)]).exit_code
        == 0
    )
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO backup_jobs(started_at, finished_at, status, target_path, error)
            VALUES (?, ?, 'failed', ?, 'boom')
            """,
            (utc_now_iso(), utc_now_iso(), str(target)),
        )
        conn.commit()
    finally:
        conn.close()

    status = get_backup_status()

    assert status.last_failure_at is not None
    assert status.last_error == "boom"


def test_backup_configure_accepts_time(runner, sv_home, tmp_path: Path) -> None:
    target = tmp_path / "timed-backups"

    result = runner.invoke(
        app,
        ["backup", "configure", "--target", str(target), "--time", "09:30", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["time"] == "09:30"


def test_backup_status_json_includes_next_due(runner, sv_home, tmp_path: Path) -> None:
    target = tmp_path / "status-backups"
    configured = runner.invoke(
        app,
        ["backup", "configure", "--target", str(target), "--time", "00:00"],
    )
    assert configured.exit_code == 0

    result = runner.invoke(app, ["backup", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schedule"] == "daily"
    assert data["time"] == "00:00"
    assert data["next_due_at"] is not None


def test_backup_configure_rejects_invalid_time(runner, sv_home, tmp_path: Path) -> None:
    target = tmp_path / "bad-time"

    result = runner.invoke(
        app,
        ["backup", "configure", "--target", str(target), "--time", "25:99"],
    )

    assert result.exit_code != 0
    assert "HH:MM" in result.output


def test_run_due_backup_waits_until_configured_time(
    runner, sv_home, project, tmp_path: Path
) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target = tmp_path / "wait-backups"
    assert (
        runner.invoke(
            app,
            ["backup", "configure", "--target", str(target), "--time", "23:59"],
        ).exit_code
        == 0
    )

    assert run_due_backup(now=datetime(2026, 7, 8, 0, 0, tzinfo=UTC)) is False


def test_run_due_backup_runs_once_per_day_after_time(
    runner, sv_home, project, tmp_path: Path
) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target = tmp_path / "daily-backups"
    assert (
        runner.invoke(
            app,
            ["backup", "configure", "--target", str(target), "--time", "00:00"],
        ).exit_code
        == 0
    )

    now = datetime(2026, 7, 8, 1, 0, tzinfo=UTC)

    assert run_due_backup(now=now) is True
    assert run_due_backup(now=now) is False


def test_run_due_backup_weekly_respects_interval_and_time() -> None:
    last = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    now = datetime(2026, 7, 8, 0, 30, tzinfo=UTC)

    next_due = next_due_after(last, "weekly", "23:59", now)

    assert next_due is not None
    assert next_due > now
