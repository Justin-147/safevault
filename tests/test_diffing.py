from __future__ import annotations

from conftest import make_symlink_or_skip
from safevault.diffing import diff_dirs
from safevault.models import DiffResult


def test_created_modified_deleted_detected(tmp_path) -> None:
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    (original / "modified.txt").write_text("old", encoding="utf-8")
    (candidate / "modified.txt").write_text("new", encoding="utf-8")
    (original / "deleted.txt").write_text("old", encoding="utf-8")
    (candidate / "created.txt").write_text("new", encoding="utf-8")
    diff = diff_dirs(original, candidate)
    changes = {entry.rel_path: entry.change_type for entry in diff.entries}
    assert changes == {
        "created.txt": "created",
        "deleted.txt": "deleted",
        "modified.txt": "modified",
    }


def test_ignored_changes_are_omitted(tmp_path) -> None:
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    (candidate / "debug.log").write_text("ignore", encoding="utf-8")
    assert diff_dirs(original, candidate).entries == []


def test_symlink_outside_root_not_followed(tmp_path) -> None:
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    make_symlink_or_skip(outside, candidate / "link")
    diff = diff_dirs(original, candidate)
    assert diff.entries[0].file_kind == "symlink"
    assert diff.entries[0].new_size != outside.stat().st_size


def test_diff_json_serialization(tmp_path) -> None:
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    (candidate / "created.txt").write_text("new", encoding="utf-8")
    diff = diff_dirs(original, candidate)
    assert DiffResult.from_dict(diff.to_dict()).entries == diff.entries
