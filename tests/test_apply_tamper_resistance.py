from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.errors import SafeVaultError
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


def test_apply_rejects_tampered_modified_git_config_with_hashes(sv_home, project) -> None:
    (project / ".git").mkdir()
    config = project / ".git" / "config"
    config.write_text("original", encoding="utf-8")
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry(
            ".git/config",
            "modified",
            "file",
            old_hash=hash_bytes(b"original"),
            new_hash=hash_bytes(b"tampered"),
        ),
        {".git/config": "tampered"},
    )
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


def test_apply_rejects_parent_escape_diff_with_hash(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("../outside.txt", "created", "file", new_hash=hash_bytes(b"new")),
    )
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


def test_created_entry_missing_new_hash_is_unsafe(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("new.txt", "created", "file"),
        {"new.txt": "new"},
    )
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert not (project / "new.txt").exists()


def test_modified_entry_missing_old_hash_is_unsafe(sv_home, project) -> None:
    (project / "a.txt").write_text("old", encoding="utf-8")
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("a.txt", "modified", "file", new_hash=hash_bytes(b"new")),
        {"a.txt": "new"},
    )
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert (project / "a.txt").read_text(encoding="utf-8") == "old"


def test_modified_entry_missing_new_hash_is_unsafe(sv_home, project) -> None:
    (project / "a.txt").write_text("old", encoding="utf-8")
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("a.txt", "modified", "file", old_hash=hash_bytes(b"old")),
        {"a.txt": "new"},
    )
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert (project / "a.txt").read_text(encoding="utf-8") == "old"


def test_deleted_entry_missing_old_hash_is_unsafe(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("old", encoding="utf-8")
    sandbox_id = _manual_sandbox(project, DiffEntry("a.txt", "deleted", "file"))
    result = apply_sandbox(sandbox_id, allow_delete=True)
    assert result.unsafe
    assert path.exists()


def test_apply_rejects_directory_source(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("dir-source", "created", "file", new_hash=hash_bytes(b"x")),
        directories=["dir-source"],
    )
    result = apply_sandbox(sandbox_id)
    assert result.unsafe


def test_apply_rejects_fifo_source_without_opening(sv_home, project) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is unavailable")
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("fifo", "created", "file", new_hash="0" * 64),
    )
    sandbox = _sandbox_work(sandbox_id)
    os.mkfifo(sandbox / "fifo")
    result = apply_sandbox(sandbox_id)
    assert result.unsafe


def test_apply_rejects_unsupported_diff_schema(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("new.txt", "created", "file", new_hash=hash_bytes(b"new")),
        diff_data={"schema_version": 2, "entries": [], "counts": {}},
    )
    with pytest.raises(SafeVaultError, match="unsupported diff schema version"):
        apply_sandbox(sandbox_id)


def test_apply_rejects_mismatched_original_root(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("new.txt", "created", "file", new_hash=hash_bytes(b"new")),
        diff_original_root=str(project.parent / "other-project"),
    )
    with pytest.raises(SafeVaultError, match="original_root"):
        apply_sandbox(sandbox_id)


def test_apply_rejects_mismatched_sandbox_root(sv_home, project) -> None:
    sandbox_id = _manual_sandbox(
        project,
        DiffEntry("new.txt", "created", "file", new_hash=hash_bytes(b"new")),
        diff_sandbox_root=str(project.parent / "other-sandbox" / "work"),
    )
    with pytest.raises(SafeVaultError, match="sandbox_root"):
        apply_sandbox(sandbox_id)


def _manual_sandbox(
    project: Path,
    entry: DiffEntry,
    files: dict[str, str] | None = None,
    directories: list[str] | None = None,
    diff_data: dict[str, object] | None = None,
    diff_original_root: str | None = None,
    diff_sandbox_root: str | None = None,
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
    diff = DiffResult(
        [entry], original_root=diff_original_root, sandbox_root=diff_sandbox_root
    )
    (sandbox_root / "diff.json").write_text(
        json.dumps(diff_data or diff.to_dict()), encoding="utf-8"
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


def _sandbox_work(sandbox_id: str) -> Path:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT sandbox_path FROM sandboxes WHERE id = ?", (sandbox_id,)
        ).fetchone()
        return Path(row["sandbox_path"])
    finally:
        conn.close()
