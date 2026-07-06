from __future__ import annotations

import json
import sys
from pathlib import Path

from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.models import DiffEntry, DiffResult
from safevault.sandbox import apply_sandbox, create_sandbox


def test_apply_created_and_modified_files(sv_home, project) -> None:
    (project / "a.txt").write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "Path('a.txt').write_text('new'); "
                "Path('b.txt').write_text('b')"
            ),
        ],
    )
    applied, deleted, skipped = apply_sandbox(sandbox_id)
    assert applied == 2
    assert deleted == 0
    assert skipped == []
    assert (project / "a.txt").read_text(encoding="utf-8") == "new"
    assert (project / "b.txt").read_text(encoding="utf-8") == "b"


def test_apply_without_allow_delete_skips_deletion(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project, [sys.executable, "-c", "from pathlib import Path; Path('a.txt').unlink()"]
    )
    _, deleted, skipped = apply_sandbox(sandbox_id)
    assert deleted == 0
    assert skipped == ["a.txt"]
    assert file_path.exists()


def test_apply_with_allow_delete_deletes_only_listed_file(sv_home, project) -> None:
    delete_me = project / "delete.txt"
    keep_me = project / "keep.txt"
    delete_me.write_text("x", encoding="utf-8")
    keep_me.write_text("y", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project, [sys.executable, "-c", "from pathlib import Path; Path('delete.txt').unlink()"]
    )
    _, deleted, skipped = apply_sandbox(sandbox_id, allow_delete=True)
    assert deleted == 1
    assert skipped == []
    assert not delete_me.exists()
    assert keep_me.exists()


def test_apply_snapshots_original_before_changing(sv_home, project) -> None:
    (project / "a.txt").write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project, [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('new')"]
    )
    apply_sandbox(sandbox_id)
    conn = connect()
    try:
        reasons = [row["reason"] for row in conn.execute("SELECT reason FROM snapshots")]
    finally:
        conn.close()
    assert "pre-apply" in reasons


def test_apply_refuses_to_delete_protected_paths(sv_home, project) -> None:
    git_dir = project / ".git"
    git_dir.mkdir()
    protected = git_dir / "config"
    protected.write_text("do not delete", encoding="utf-8")
    sandbox_id = _manual_sandbox(project, DiffResult([DiffEntry(".git/config", "deleted", "file")]))
    result = apply_sandbox(sandbox_id, allow_delete=True)
    assert result.deleted == 0
    assert result.unsafe
    assert protected.exists()


def test_missing_sandbox_id_fails_clearly(runner, sv_home) -> None:
    from safevault.cli import app

    result = runner.invoke(app, ["apply", "missing"])
    assert result.exit_code != 0
    assert "sandbox not found" in result.output


def _manual_sandbox(project: Path, diff: DiffResult) -> str:
    sandbox_id = "manual-sandbox"
    sandbox_work = project.parent / "manual-work"
    sandbox_work.mkdir()
    diff_path = sandbox_work.parent / "diff.json"
    diff_path.write_text(json.dumps(diff.to_dict()), encoding="utf-8")
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
    return sandbox_id
