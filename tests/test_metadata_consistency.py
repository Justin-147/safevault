from __future__ import annotations

import json
import sys
from pathlib import Path

from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.models import DiffEntry, DiffResult
from safevault.restore import restore_file
from safevault.sandbox import apply_sandbox, create_sandbox
from safevault.snapshot import create_snapshot


def test_restore_marks_file_active_and_records_restored_content(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    path.unlink()
    create_snapshot(project)
    restore_file(path, latest=True)
    conn = connect()
    try:
        file_row = conn.execute("SELECT * FROM files WHERE rel_path = 'a.txt'").fetchone()
        reasons = [row["reason"] for row in conn.execute("SELECT reason FROM snapshots")]
    finally:
        conn.close()
    assert file_row["status"] == "active"
    assert "post-restore" in reasons


def test_apply_modified_file_is_captured_in_versions(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project, [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('new')"]
    )
    apply_sandbox(sandbox_id)
    conn = connect()
    try:
        version_count = int(conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0])
        reasons = [row["reason"] for row in conn.execute("SELECT reason FROM snapshots")]
    finally:
        conn.close()
    assert version_count >= 2
    assert "post-apply" in reasons


def test_apply_created_file_is_tracked(sv_home, project) -> None:
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('created.txt').write_text('new')"],
    )
    apply_sandbox(sandbox_id)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM files WHERE rel_path = 'created.txt'").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["status"] == "active"


def test_unsafe_apply_does_not_claim_applied(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(project, DiffEntry(".git/config", "created", "file"))
    apply_sandbox(sandbox_id)
    conn = connect()
    try:
        row = conn.execute("SELECT status FROM sandboxes WHERE id = ?", (sandbox_id,)).fetchone()
        status = row["status"]
    finally:
        conn.close()
    assert status == "partially_applied"


def _manual_sandbox(project: Path, entry: DiffEntry) -> str:
    sandbox_id = "metadata-unsafe"
    sandbox_root = project.parent / sandbox_id
    sandbox_work = sandbox_root / "work"
    sandbox_work.mkdir(parents=True)
    (sandbox_root / "diff.json").write_text(
        json.dumps(DiffResult([entry]).to_dict()), encoding="utf-8"
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
    return sandbox_id
