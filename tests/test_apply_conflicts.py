from __future__ import annotations

import json
import sys
from pathlib import Path

from safevault.cli import app
from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.hashing import hash_bytes
from safevault.models import DiffEntry, DiffResult
from safevault.sandbox import apply_sandbox, create_sandbox, get_sandbox


def test_modified_original_conflicts_and_preserves_user_version(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('sandbox')"],
    )
    file_path.write_text("user", encoding="utf-8")
    result = apply_sandbox(sandbox_id)
    assert result.conflicts == ["a.txt"]
    assert file_path.read_text(encoding="utf-8") == "user"


def test_deleted_original_conflicts_and_preserves_user_version(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project, [sys.executable, "-c", "from pathlib import Path; Path('a.txt').unlink()"]
    )
    file_path.write_text("user", encoding="utf-8")
    result = apply_sandbox(sandbox_id, allow_delete=True)
    assert result.conflicts == ["a.txt"]
    assert file_path.read_text(encoding="utf-8") == "user"


def test_created_file_conflicts_if_user_created_it_first(sv_home, project) -> None:
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('new.txt').write_text('sandbox')"],
    )
    (project / "new.txt").write_text("user", encoding="utf-8")
    result = apply_sandbox(sandbox_id)
    assert result.conflicts == ["new.txt"]
    assert (project / "new.txt").read_text(encoding="utf-8") == "user"


def test_non_conflicting_modified_file_applies(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('sandbox')"],
    )
    result = apply_sandbox(sandbox_id)
    assert not result.conflicts
    assert file_path.read_text(encoding="utf-8") == "sandbox"


def test_cli_output_mentions_conflict(runner, sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('sandbox')"],
    )
    file_path.write_text("user", encoding="utf-8")
    result = runner.invoke(app, ["apply", sandbox_id])
    assert result.exit_code == 2
    assert "Conflicts" in result.output


def test_cli_apply_exit_0_for_skipped_deletion_only(runner, sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project, [sys.executable, "-c", "from pathlib import Path; Path('a.txt').unlink()"]
    )
    result = runner.invoke(app, ["apply", sandbox_id])
    assert result.exit_code == 0
    assert "Skipped deletions" in result.output
    assert file_path.exists()


def test_apply_dry_run_does_not_modify_files_or_status(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('sandbox')"],
    )
    before_snapshots, before_status = _snapshot_count_and_status(sandbox_id)
    result = apply_sandbox(sandbox_id, dry_run=True)
    after_snapshots, after_status = _snapshot_count_and_status(sandbox_id)
    assert result.applied == 1
    assert file_path.read_text(encoding="utf-8") == "old"
    assert after_snapshots == before_snapshots
    assert after_status == before_status == "complete"


def test_cli_apply_dry_run_reports_conflict(runner, sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('sandbox')"],
    )
    file_path.write_text("user", encoding="utf-8")
    result = runner.invoke(app, ["apply", sandbox_id, "--dry-run"])
    assert result.exit_code == 2
    assert "Dry run: no files changed" in result.output
    assert "Conflicts" in result.output
    assert file_path.read_text(encoding="utf-8") == "user"


def test_cli_apply_exit_2_for_unsafe_entry(runner, sv_home, project) -> None:
    sandbox_id = _manual_sandbox(project, DiffEntry(".git/config", "created", "file"))
    result = runner.invoke(app, ["apply", sandbox_id])
    assert result.exit_code == 2
    assert "Unsafe entries" in result.output


def test_cli_apply_exit_2_for_missing_sandbox_source(runner, sv_home, project) -> None:
    sandbox_id = _manual_sandbox(
        project, DiffEntry("missing.txt", "created", "file", new_hash=hash_bytes(b"new"))
    )
    result = runner.invoke(app, ["apply", sandbox_id])
    assert result.exit_code == 2
    assert "Missing sandbox sources" in result.output


def _snapshot_count_and_status(sandbox_id: str) -> tuple[int, str]:
    conn = connect()
    try:
        snapshot_count = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
        status = str(
            conn.execute(
                "SELECT status FROM sandboxes WHERE id = ?", (sandbox_id,)
            ).fetchone()["status"]
        )
    finally:
        conn.close()
    return snapshot_count, status


def _manual_sandbox(project: Path, entry: DiffEntry) -> str:
    sandbox_id = f"manual-cli-{abs(hash(entry.rel_path))}"
    sandbox_root = project.parent / sandbox_id
    sandbox_work = sandbox_root / "work"
    sandbox_work.mkdir(parents=True)
    (sandbox_root / "diff.json").write_text(
        json.dumps(
            DiffResult(
                [entry],
                original_root=str(project.resolve()),
                sandbox_root=str(sandbox_work.resolve()),
            ).to_dict()
        ),
        encoding="utf-8",
    )
    conn = connect()
    try:
        root_id = get_or_create_root(conn, project, "coding")
        conn.execute(
            """
            INSERT INTO sandboxes(id, root_id, original_path, sandbox_path, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sandbox_id, root_id, str(project), str(sandbox_work), utc_now_iso(), "complete"),
        )
        conn.commit()
    finally:
        conn.close()
    assert Path(get_sandbox(sandbox_id).sandbox_path) == sandbox_work
    return sandbox_id
