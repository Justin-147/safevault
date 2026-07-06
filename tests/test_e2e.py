from __future__ import annotations

import sys

from safevault.db import connect
from safevault.restore import restore_file
from safevault.sandbox import apply_sandbox, create_sandbox
from safevault.snapshot import create_snapshot


def test_init_snapshot_delete_snapshot_restore_flow(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("v1", encoding="utf-8")
    create_snapshot(project, reason="initial")
    file_path.unlink()
    create_snapshot(project, reason="after-delete")
    restore_file(file_path, latest=True)
    assert file_path.read_text(encoding="utf-8") == "v1"


def test_restore_v1_by_version_id_after_v2(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    v1 = _first_version_id()
    file_path.write_text("v2", encoding="utf-8")
    create_snapshot(project)
    restore_file(file_path, version_id=v1)
    assert file_path.read_text(encoding="utf-8") == "v1"


def test_run_delete_keeps_original_then_apply_delete_modes(sv_home, project) -> None:
    file_path = project / "important.txt"
    file_path.write_text("important", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project, [sys.executable, "-c", "from pathlib import Path; Path('important.txt').unlink()"]
    )
    assert file_path.exists()
    apply_sandbox(sandbox_id)
    assert file_path.exists()
    apply_sandbox(sandbox_id, allow_delete=True)
    assert not file_path.exists()


def test_apply_without_delete_still_adds_created_file(sv_home, project) -> None:
    (project / "important.txt").write_text("important", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "Path('important.txt').unlink(); "
                "Path('new.txt').write_text('new')"
            ),
        ],
    )
    apply_sandbox(sandbox_id)
    assert (project / "important.txt").exists()
    assert (project / "new.txt").read_text(encoding="utf-8") == "new"


def _first_version_id() -> int:
    conn = connect()
    try:
        return int(conn.execute("SELECT id FROM versions ORDER BY id LIMIT 1").fetchone()["id"])
    finally:
        conn.close()
