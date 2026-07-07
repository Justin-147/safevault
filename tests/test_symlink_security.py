from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from conftest import make_symlink_or_skip
from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.hashing import hash_bytes, hash_symlink_target
from safevault.models import DiffEntry, DiffResult
from safevault.safety import symlink_target_stays_within
from safevault.sandbox import apply_sandbox, create_sandbox, get_sandbox
from safevault.symlinks import external_symlink_placeholder_payload


def test_external_project_symlink_is_not_active_in_sandbox(sv_home, project, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    make_symlink_or_skip(outside, project / "outside-link")
    sandbox_id, _, _, _ = create_sandbox(project, [sys.executable, "-c", "print('ok')"])
    sandbox_link = Path(get_sandbox(sandbox_id).sandbox_path) / "outside-link"
    assert sandbox_link.is_file()
    assert not sandbox_link.is_symlink()
    assert sandbox_link.read_text(encoding="utf-8").startswith("SAFEVAULT_EXTERNAL_SYMLINK")


def test_sandbox_command_cannot_write_through_external_symlink(sv_home, project, tmp_path) -> None:
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


def test_apply_skips_malicious_created_symlink_to_outside(sv_home, project, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    sandbox_id = _manual_symlink_sandbox(project, "bad-link", str(outside))
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert not (project / "bad-link").exists()


def test_internal_relative_symlink_remains_safe(sv_home, project) -> None:
    target = project / "target.txt"
    target.write_text("target", encoding="utf-8")
    make_symlink_or_skip(Path("target.txt"), project / "link")
    sandbox_id, _, _, _ = create_sandbox(project, [sys.executable, "-c", "print('ok')"])
    sandbox_link = Path(get_sandbox(sandbox_id).sandbox_path) / "link"
    if sandbox_link.is_symlink():
        assert symlink_target_stays_within(
            Path(get_sandbox(sandbox_id).sandbox_path),
            sandbox_link,
            os.readlink(sandbox_link),
        )
    else:
        assert sandbox_link.is_file()


def test_run_does_not_report_unchanged_external_symlink_as_modified(
    sv_home, project, tmp_path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    make_symlink_or_skip(outside, project / "outside-link")
    _, _, diff, _ = create_sandbox(project, [sys.executable, "-c", "print('ok')"])
    assert "outside-link" not in {entry.rel_path for entry in diff.entries}


def test_apply_preserves_original_external_symlink(sv_home, project, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = project / "outside-link"
    make_symlink_or_skip(outside, link)
    sandbox_id, _, _, _ = create_sandbox(project, [sys.executable, "-c", "print('ok')"])
    result = apply_sandbox(sandbox_id)
    assert not result.unsafe
    assert link.is_symlink()
    assert Path(os.readlink(link)) == outside


def test_modified_external_symlink_placeholder_is_unsafe(sv_home, project, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = project / "outside-link"
    make_symlink_or_skip(outside, link)
    payload = external_symlink_placeholder_payload(str(tmp_path / "other.txt"))
    sandbox_id = _manual_placeholder_sandbox(
        project,
        "outside-link",
        payload,
        DiffEntry(
            "outside-link",
            "modified",
            "file",
            old_hash=hash_symlink_target(str(outside)),
            new_hash=hash_bytes(payload),
        ),
    )
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert link.is_symlink()
    assert Path(os.readlink(link)) == outside


def test_apply_rejects_regular_file_over_original_external_symlink(
    sv_home, project, tmp_path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = project / "outside-link"
    make_symlink_or_skip(outside, link)
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [
            sys.executable,
            "-c",
            "from pathlib import Path; Path('outside-link').write_text('sandbox')",
        ],
    )
    result = apply_sandbox(sandbox_id)
    assert result.unsafe
    assert link.is_symlink()
    assert Path(os.readlink(link)) == outside
    assert outside.read_text(encoding="utf-8") == "outside"


def _manual_symlink_sandbox(project: Path, rel_path: str, target: str) -> str:
    sandbox_id = "manual-symlink"
    sandbox_root = project.parent / sandbox_id
    sandbox_work = sandbox_root / "work"
    sandbox_work.mkdir(parents=True)
    link = sandbox_work / rel_path
    make_symlink_or_skip(Path(target), link)
    diff = DiffResult(
        [DiffEntry(rel_path, "created", "symlink", new_hash=hash_symlink_target(target))]
    )
    (sandbox_root / "diff.json").write_text(json.dumps(diff.to_dict()), encoding="utf-8")
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


def _manual_placeholder_sandbox(
    project: Path, rel_path: str, payload: bytes, entry: DiffEntry
) -> str:
    sandbox_id = "manual-placeholder"
    sandbox_root = project.parent / sandbox_id
    sandbox_work = sandbox_root / "work"
    sandbox_work.mkdir(parents=True)
    source = sandbox_work / rel_path
    source.write_bytes(payload)
    diff = DiffResult([entry])
    (sandbox_root / "diff.json").write_text(json.dumps(diff.to_dict()), encoding="utf-8")
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
