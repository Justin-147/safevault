from __future__ import annotations

import json
import sys
from pathlib import Path

from conftest import make_symlink_or_skip
from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.models import DiffEntry, DiffResult
from safevault.restore import restore_file
from safevault.sandbox import apply_sandbox, create_sandbox
from safevault.snapshot import create_snapshot


def test_hardened_init_snapshot_delete_restore(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    path.unlink()
    create_snapshot(project)
    restore_file(path, latest=True)
    assert path.read_text(encoding="utf-8") == "v1"


def test_hardened_run_delete_preserves_original_and_apply_modes(sv_home, project) -> None:
    path = project / "important.txt"
    path.write_text("important", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project, [sys.executable, "-c", "from pathlib import Path; Path('important.txt').unlink()"]
    )
    assert path.exists()
    apply_sandbox(sandbox_id)
    assert path.exists()
    apply_sandbox(sandbox_id, allow_delete=True)
    assert not path.exists()


def test_hardened_conflict_preserves_original(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('sandbox')"],
    )
    path.write_text("user", encoding="utf-8")
    result = apply_sandbox(sandbox_id)
    assert result.conflicts
    assert path.read_text(encoding="utf-8") == "user"


def test_hardened_external_symlink_cannot_modify_outside(sv_home, project, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    make_symlink_or_skip(outside, project / "outside-link")
    create_sandbox(
        project,
        [
            sys.executable,
            "-c",
            "from pathlib import Path; Path('outside-link').write_text('sandbox')",
        ],
    )
    assert outside.read_text(encoding="utf-8") == "outside"


def test_hardened_tampered_git_config_is_rejected(sv_home, project) -> None:
    (project / ".git").mkdir()
    config = project / ".git" / "config"
    config.write_text("keep", encoding="utf-8")
    sandbox_id = _manual_sandbox(project, DiffEntry(".git/config", "modified", "file"))
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert config.read_text(encoding="utf-8") == "keep"


def test_hardened_large_file_snapshot_and_restore(sv_home, project, monkeypatch) -> None:
    path = project / "large.bin"
    data = b"0123456789abcdef" * 200_000
    path.write_bytes(data)
    create_snapshot(project)
    path.unlink()

    def fail_read_bytes(self: Path) -> bytes:
        raise AssertionError(f"read_bytes should not be needed for restore: {self}")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    restore_file(path, latest=True)
    with path.open("rb") as file_obj:
        assert file_obj.read() == data


def _manual_sandbox(project: Path, entry: DiffEntry) -> str:
    sandbox_id = "hardened-manual"
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
