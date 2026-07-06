from __future__ import annotations

import json
from pathlib import Path

from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.hashing import hash_bytes
from safevault.models import DiffEntry, DiffResult
from safevault.sandbox import apply_sandbox


def test_tampered_diff_rejects_git_config(sv_home, project) -> None:
    (project / ".git").mkdir()
    config = project / ".git" / "config"
    config.write_text("original", encoding="utf-8")
    sandbox_id = _manual_sandbox(project, DiffEntry(".git/config", "modified", "file"))
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert config.read_text(encoding="utf-8") == "original"


def test_tampered_diff_rejects_safevault_db_path(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(project, DiffEntry(".safevault/vault.db", "created", "file"))
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert not (project / ".safevault" / "vault.db").exists()


def test_tampered_diff_rejects_parent_escape_without_partial_write(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(project, DiffEntry("../outside.txt", "created", "file"))
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert not (project.parent / "outside.txt").exists()


def test_tampered_new_hash_is_rejected(sv_home, project) -> None:
    source_file = project / "src" / "app.py"
    source_file.parent.mkdir()
    source_file.write_text("old", encoding="utf-8")
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("src/app.py", "modified", "file", old_hash=hash_bytes(b"old"), new_hash="0" * 64),
        {"src/app.py": "new"},
    )
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert source_file.read_text(encoding="utf-8") == "old"


def test_unknown_change_type_is_rejected(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(project, DiffEntry("src/app.py", "rewrite", "file"))
    result = apply_sandbox(sandbox_id)
    assert result.unsafe


def test_sandbox_directory_as_file_is_rejected(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("src/app.py", "created", "file", new_hash=hash_bytes(b"x")),
        directories=["src/app.py"],
    )
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert not (project / "src" / "app.py").exists()


def _manual_sandbox(
    project: Path,
    entry: DiffEntry,
    files: dict[str, str] | None = None,
    directories: list[str] | None = None,
) -> str:
    sandbox_id = f"manual-{abs(hash(entry.rel_path))}"
    sandbox_root = project.parent / sandbox_id
    sandbox_work = sandbox_root / "work"
    sandbox_work.mkdir(parents=True)
    for rel_path, content in (files or {}).items():
        target = sandbox_work / Path(*rel_path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for rel_path in directories or []:
        (sandbox_work / Path(*rel_path.split("/"))).mkdir(parents=True)
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
