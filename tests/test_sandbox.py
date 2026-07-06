from __future__ import annotations

import json
import sys
from pathlib import Path

from safevault.db import connect
from safevault.sandbox import create_sandbox


def test_run_creates_sandbox_and_modifies_only_sandbox(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("original", encoding="utf-8")
    sandbox_id, returncode, diff, diff_path = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('changed')"],
    )
    assert sandbox_id
    assert returncode == 0
    assert file_path.read_text(encoding="utf-8") == "original"
    assert diff_path.is_file()
    assert diff.by_type("modified")


def test_command_deleting_file_deletes_only_sandbox(sv_home, project) -> None:
    file_path = project / "important.txt"
    file_path.write_text("important", encoding="utf-8")
    _, _, diff, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('important.txt').unlink()"],
    )
    assert file_path.exists()
    assert diff.by_type("deleted")


def test_diff_json_records_created_modified_deleted(sv_home, project) -> None:
    (project / "a.txt").write_text("a", encoding="utf-8")
    (project / "b.txt").write_text("b", encoding="utf-8")
    _, _, _, diff_path = create_sandbox(
        project,
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "Path('a.txt').write_text('aa'); "
                "Path('b.txt').unlink(); "
                "Path('c.txt').write_text('c')"
            ),
        ],
    )
    data = json.loads(diff_path.read_text(encoding="utf-8"))
    changes = {entry["change_type"] for entry in data["entries"]}
    assert {"created", "modified", "deleted"} <= changes


def test_ignored_directories_are_not_copied(sv_home, project) -> None:
    ignored = project / "node_modules"
    ignored.mkdir()
    (ignored / "package.js").write_text("x", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(project, [sys.executable, "-c", "print('ok')"])
    sandbox_work = _sandbox_work(sandbox_id)
    assert not (sandbox_work / "node_modules").exists()


def test_nonzero_command_still_records_sandbox_metadata(sv_home, project) -> None:
    sandbox_id, returncode, _, _ = create_sandbox(
        project, [sys.executable, "-c", "raise SystemExit(7)"]
    )
    assert returncode == 7
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM sandboxes WHERE id = ?", (sandbox_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["status"] == "command_failed"


def _sandbox_work(sandbox_id: str) -> Path:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT sandbox_path FROM sandboxes WHERE id = ?", (sandbox_id,)
        ).fetchone()
        return Path(row["sandbox_path"])
    finally:
        conn.close()
