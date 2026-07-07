from __future__ import annotations

from conftest import make_symlink_or_skip
from safevault import __version__
from safevault.diffing import diff_dirs
from safevault.errors import SafeVaultError
from safevault.models import DiffResult
from safevault.symlinks import external_symlink_placeholder_payload


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


def test_diff_json_includes_schema_and_metadata(tmp_path) -> None:
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    (candidate / "created.txt").write_text("new", encoding="utf-8")
    data = diff_dirs(original, candidate).to_dict()
    assert data["schema_version"] == 1
    assert data["original_root"] == str(original.resolve())
    assert data["sandbox_root"] == str(candidate.resolve())
    assert data["safevault_version"] == __version__
    assert isinstance(data["created_at"], str)
    assert data["counts"] == {"created": 1, "modified": 0, "deleted": 0}


def test_diff_json_rejects_unsupported_schema() -> None:
    try:
        DiffResult.from_dict({"schema_version": 999, "entries": []})
    except SafeVaultError as exc:
        assert "unsupported diff schema version" in str(exc)
    else:
        raise AssertionError("unsupported schema should fail")


def test_external_symlink_placeholder_is_unchanged_in_diff(tmp_path) -> None:
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    outside = tmp_path / "outside.txt"
    original.mkdir()
    candidate.mkdir()
    outside.write_text("secret", encoding="utf-8")
    make_symlink_or_skip(outside, original / "outside-link")
    (candidate / "outside-link").write_bytes(
        external_symlink_placeholder_payload(str(outside))
    )
    assert diff_dirs(original, candidate).entries == []


def test_modified_external_symlink_placeholder_is_reported(tmp_path) -> None:
    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    outside = tmp_path / "outside.txt"
    original.mkdir()
    candidate.mkdir()
    outside.write_text("secret", encoding="utf-8")
    make_symlink_or_skip(outside, original / "outside-link")
    (candidate / "outside-link").write_bytes(
        external_symlink_placeholder_payload(str(tmp_path / "other.txt"))
    )
    diff = diff_dirs(original, candidate)
    assert [entry.rel_path for entry in diff.entries] == ["outside-link"]
