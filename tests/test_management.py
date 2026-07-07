from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from safevault.cli import app
from safevault.db import connect, get_or_create_root
from safevault.paths import get_sandboxes_dir
from safevault.snapshot import create_snapshot


def test_status_shows_root_snapshot_counts_and_health(runner, sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    result = runner.invoke(app, ["status", str(project / "a.txt")])
    assert result.exit_code == 0
    assert "Protected root" in result.output
    assert "Tracked active files" in result.output
    assert "Health" in result.output


def test_roots_lists_initialized_root(runner, sv_home, project) -> None:
    result = runner.invoke(app, ["init", str(project)])
    assert result.exit_code == 0
    result = runner.invoke(app, ["roots"])
    assert result.exit_code == 0
    assert str(project.resolve()) in result.output
    assert "coding" in result.output


def test_unprotect_removes_root_metadata_only(runner, sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    result = runner.invoke(app, ["unprotect", str(project)])
    assert result.exit_code == 0
    assert path.exists()
    result = runner.invoke(app, ["status", str(project)])
    assert result.exit_code != 0
    assert "protected root" in result.output


def test_sandbox_clean_removes_only_matching_old_status(runner, sv_home, project) -> None:
    old_applied = _manual_sandbox(project, "old-applied", "applied", days_old=45)
    old_complete = _manual_sandbox(project, "old-complete", "complete", days_old=45)
    recent_applied = _manual_sandbox(project, "recent-applied", "applied", days_old=1)
    result = runner.invoke(
        app,
        ["sandbox-clean", "--older-than", "30d", "--status", "applied"],
    )
    assert result.exit_code == 0
    assert "Cleaned sandboxes: 1" in result.output
    assert not old_applied.exists()
    assert old_complete.exists()
    assert recent_applied.exists()


def test_sandbox_clean_dry_run_keeps_directory(runner, sv_home, project) -> None:
    old_applied = _manual_sandbox(project, "dry-run-applied", "applied", days_old=45)
    result = runner.invoke(
        app,
        ["sandbox-clean", "--older-than", "30d", "--status", "applied", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Would clean sandboxes: 1" in result.output
    assert old_applied.exists()


def _manual_sandbox(project: Path, sandbox_id: str, status: str, *, days_old: int) -> Path:
    sandboxes_root = get_sandboxes_dir()
    sandbox_dir = sandboxes_root / sandbox_id
    sandbox_work = sandbox_dir / "work"
    sandbox_work.mkdir(parents=True)
    created_at = (datetime.now(UTC) - timedelta(days=days_old)).isoformat(
        timespec="microseconds"
    )
    conn = connect()
    try:
        root_id = get_or_create_root(conn, project, "coding")
        conn.execute(
            """
            INSERT INTO sandboxes(id, root_id, original_path, sandbox_path, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sandbox_id, root_id, str(project.resolve()), str(sandbox_work), created_at, status),
        )
        conn.commit()
    finally:
        conn.close()
    return sandbox_dir
