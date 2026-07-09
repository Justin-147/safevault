from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from conftest import make_symlink_or_skip
from safevault.cli import app
from safevault.db import connect, get_or_create_root
from safevault.object_store import object_path
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
    result = runner.invoke(app, ["status", str(project), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["protected_root"] == str(project.resolve())


def test_roots_lists_initialized_root(runner, sv_home, project) -> None:
    result = runner.invoke(app, ["init", str(project)])
    assert result.exit_code == 0
    result = runner.invoke(app, ["roots"])
    assert result.exit_code == 0
    assert str(project.resolve()) in result.output
    assert "coding" in result.output
    result = runner.invoke(app, ["roots", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)[0]["path"] == str(project.resolve())


def test_unprotect_without_confirm_fails_and_keeps_root(runner, sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    result = runner.invoke(app, ["unprotect", str(project)])
    assert result.exit_code != 0
    assert path.exists()
    result = runner.invoke(app, ["status", str(project)])
    assert result.exit_code == 0


def test_unprotect_dry_run_prints_counts_and_keeps_root(runner, sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    result = runner.invoke(app, ["unprotect", str(project), "--dry-run"])
    assert result.exit_code == 0
    assert "Files rows" in result.output
    assert "Object-store content files will not be deleted" in result.output
    result = runner.invoke(app, ["status", str(project)])
    assert result.exit_code == 0


def test_unprotect_confirm_removes_metadata_but_keeps_objects(runner, sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    digest = _first_hash()
    result = runner.invoke(app, ["unprotect", str(project), "--confirm"])
    assert result.exit_code == 0
    assert path.exists()
    assert object_path(digest).exists()
    result = runner.invoke(app, ["status", str(project)])
    assert result.exit_code != 0
    assert "protected root" in result.output
    conn = connect()
    try:
        for table in (
            "file_events",
            "version_timeline",
            "restore_points",
            "ai_change_sessions",
        ):
            assert int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) == 0
    finally:
        conn.close()


def test_unprotect_dry_run_json(runner, sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    result = runner.invoke(app, ["unprotect", str(project), "--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["dry_run"] is True
    assert data["object_store_deleted"] is False


def test_sandbox_clean_defaults_to_dry_run(runner, sv_home, project) -> None:
    old_applied = _manual_sandbox(project, "old-applied", "applied", days_old=45)
    old_complete = _manual_sandbox(project, "old-complete", "complete", days_old=45)
    recent_applied = _manual_sandbox(project, "recent-applied", "applied", days_old=1)
    result = runner.invoke(
        app,
        ["sandbox-clean", "--older-than", "30d", "--status", "applied"],
    )
    assert result.exit_code == 0
    assert "Would clean sandboxes: 1" in result.output
    assert old_applied.exists()
    assert old_complete.exists()
    assert recent_applied.exists()


def test_sandbox_clean_confirm_removes_applied_old_status(runner, sv_home, project) -> None:
    old_applied = _manual_sandbox(project, "old-applied-confirm", "applied", days_old=45)
    result = runner.invoke(
        app,
        ["sandbox-clean", "--older-than", "30d", "--status", "applied", "--confirm"],
    )
    assert result.exit_code == 0
    assert "Cleaned sandboxes: 1" in result.output
    assert not old_applied.exists()


def test_sandbox_clean_dry_run_keeps_directory(runner, sv_home, project) -> None:
    old_applied = _manual_sandbox(project, "dry-run-applied", "applied", days_old=45)
    result = runner.invoke(
        app,
        ["sandbox-clean", "--older-than", "30d", "--status", "applied", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Would clean sandboxes: 1" in result.output
    assert old_applied.exists()


def test_sandbox_clean_refuses_running_without_override(runner, sv_home, project) -> None:
    running = _manual_sandbox(project, "running-sandbox", "running", days_old=45)
    result = runner.invoke(
        app,
        ["sandbox-clean", "--older-than", "30d", "--status", "running", "--confirm"],
    )
    assert result.exit_code != 0
    assert running.exists()


def test_sandbox_clean_override_can_clean_non_applied(runner, sv_home, project) -> None:
    command_failed = _manual_sandbox(
        project, "command-failed-sandbox", "command_failed", days_old=45
    )
    result = runner.invoke(
        app,
        [
            "sandbox-clean",
            "--older-than",
            "30d",
            "--status",
            "command_failed",
            "--include-non-applied",
            "--confirm",
        ],
    )
    assert result.exit_code == 0
    assert not command_failed.exists()


def test_sandbox_clean_does_not_follow_symlink_directory(
    runner, sv_home, project, tmp_path
) -> None:
    sandbox_dir = _manual_sandbox(project, "symlink-sandbox", "applied", days_old=45)
    target = tmp_path / "target"
    target.mkdir()
    shutil.rmtree(sandbox_dir)
    make_symlink_or_skip(target, sandbox_dir)
    result = runner.invoke(
        app,
        ["sandbox-clean", "--older-than", "30d", "--status", "applied", "--confirm"],
    )
    assert result.exit_code == 0
    assert sandbox_dir.is_symlink()
    assert target.exists()


def test_sandbox_clean_dry_run_json(runner, sv_home, project) -> None:
    _manual_sandbox(project, "json-sandbox", "applied", days_old=45)
    result = runner.invoke(
        app,
        ["sandbox-clean", "--older-than", "30d", "--status", "applied", "--dry-run", "--json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["dry_run"] is True
    assert data["cleaned"] == 1


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


def _first_hash() -> str:
    conn = connect()
    try:
        return str(conn.execute("SELECT content_hash FROM versions").fetchone()["content_hash"])
    finally:
        conn.close()
