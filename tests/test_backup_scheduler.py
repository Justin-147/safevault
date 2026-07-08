from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from safevault.backup import get_backup_status, run_due_backup
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
        ["backup", "configure", "--target", str(target), "--schedule", "daily", "--json"],
    )
    assert configured.exit_code == 0
    assert json.loads(configured.output)["enabled"] is True

    result = runner.invoke(app, ["backup", "run", "--json"])
    assert result.exit_code == 0
    output = Path(json.loads(result.output)["output"])
    assert output.is_file()
    assert (target / "safevault-latest.tar.gz").is_file()

    status = runner.invoke(app, ["backup", "status", "--json"])
    assert status.exit_code == 0
    assert json.loads(status.output)["last_success_at"] is not None

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


def test_due_backup_runs_after_interval(runner, sv_home, project, tmp_path: Path) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target = tmp_path / "scheduled-backups"
    assert (
        runner.invoke(app, ["backup", "configure", "--target", str(target)]).exit_code
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
        runner.invoke(app, ["backup", "configure", "--target", str(target)]).exit_code
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
