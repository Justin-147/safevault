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


def test_run_writes_placeholder_sidecar_for_external_symlink(
    sv_home, project, tmp_path
) -> None:
    from conftest import make_symlink_or_skip

    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    make_symlink_or_skip(outside, project / "outside-link")
    sandbox_id, _, _, _ = create_sandbox(project, [sys.executable, "-c", "print('ok')"])
    sandbox_work = _sandbox_work(sandbox_id)
    sidecar = sandbox_work.parent / "placeholder-map.json"
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["external_symlink_placeholders"] == {"outside-link": str(outside)}


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


def test_ai_command_records_before_restore_point_and_session(
    sv_home, project, tmp_path
) -> None:
    target = project / "ai.txt"
    target.write_text("original", encoding="utf-8")
    script = tmp_path / "codex.py"
    script.write_text(
        "from pathlib import Path\nPath('ai.txt').write_text('changed')\n",
        encoding="utf-8",
    )

    sandbox_id, returncode, diff, _ = create_sandbox(project, [sys.executable, str(script)])

    assert returncode == 0
    assert diff.by_type("modified")
    conn = connect()
    try:
        session = conn.execute(
            "SELECT * FROM ai_change_sessions WHERE sandbox_id = ?", (sandbox_id,)
        ).fetchone()
        restore_point = conn.execute(
            """
            SELECT rp.*
            FROM restore_points rp
            JOIN snapshots s ON s.id = rp.snapshot_id
            WHERE s.reason = 'before-ai-change'
            """
        ).fetchone()
    finally:
        conn.close()
    assert session is not None
    assert session["tool_name"] == "codex"
    assert session["modified_count"] == 1
    assert session["status"] == "sandbox_complete"
    assert restore_point is not None
    assert restore_point["important"] == 1


def test_applying_ai_sandbox_records_after_restore_point(sv_home, project, tmp_path) -> None:
    target = project / "apply-ai.txt"
    target.write_text("before", encoding="utf-8")
    script = tmp_path / "cursor.py"
    script.write_text(
        "from pathlib import Path\nPath('apply-ai.txt').write_text('after')\n",
        encoding="utf-8",
    )
    sandbox_id, _, _, _ = create_sandbox(project, [sys.executable, str(script)])

    from safevault.sandbox import apply_sandbox

    result = apply_sandbox(sandbox_id)

    assert result.applied == 1
    assert target.read_text(encoding="utf-8") == "after"
    conn = connect()
    try:
        reasons = [
            str(row["reason"])
            for row in conn.execute("SELECT reason FROM snapshots ORDER BY id").fetchall()
        ]
        session = conn.execute(
            "SELECT * FROM ai_change_sessions WHERE sandbox_id = ?", (sandbox_id,)
        ).fetchone()
        after_point = conn.execute(
            """
            SELECT rp.*
            FROM restore_points rp
            JOIN snapshots s ON s.id = rp.snapshot_id
            WHERE s.reason = 'after-ai-change'
            """
        ).fetchone()
    finally:
        conn.close()
    assert "before-ai-change" in reasons
    assert "after-ai-change" in reasons
    assert session["tool_name"] == "cursor"
    assert session["status"] == "applied"
    assert session["after_snapshot_id"] is not None
    assert after_point is not None
    assert after_point["important"] == 1


def test_sandboxes_json_output(runner, sv_home, project) -> None:
    sandbox_id, _, _, _ = create_sandbox(project, [sys.executable, "-c", "print('ok')"])
    from safevault.cli import app

    result = runner.invoke(app, ["sandboxes", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["id"] == sandbox_id


def _sandbox_work(sandbox_id: str) -> Path:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT sandbox_path FROM sandboxes WHERE id = ?", (sandbox_id,)
        ).fetchone()
        return Path(row["sandbox_path"])
    finally:
        conn.close()
