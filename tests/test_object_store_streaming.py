from __future__ import annotations

from pathlib import Path

import pytest

from safevault.object_store import iter_object_hashes, object_path, open_object, store_file


def test_store_file_works_on_multi_megabyte_file(sv_home, tmp_path) -> None:
    path = tmp_path / "large.bin"
    data = b"abc123" * 400_000
    path.write_bytes(data)
    digest = store_file(path)
    with open_object(digest) as file_obj:
        assert file_obj.read() == data


def test_store_file_does_not_use_path_read_bytes(sv_home, tmp_path, monkeypatch) -> None:
    path = tmp_path / "large.bin"
    path.write_bytes(b"x" * (2 * 1024 * 1024))

    def fail_read_bytes(self: Path) -> bytes:
        raise AssertionError(f"read_bytes should not be used for {self}")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    digest = store_file(path)
    assert object_path(digest).is_file()


def test_identical_large_files_create_one_object(sv_home, tmp_path) -> None:
    data = b"same" * 800_000
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(data)
    second.write_bytes(data)
    assert store_file(first) == store_file(second)
    assert len(list(iter_object_hashes())) == 1


def test_exception_during_store_leaves_no_valid_object(sv_home, tmp_path, monkeypatch) -> None:
    path = tmp_path / "file.bin"
    path.write_bytes(b"payload")

    def fail_fsync(_file_obj) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr("safevault.object_store.fsync_file", fail_fsync)
    with pytest.raises(OSError):
        store_file(path)
    assert list(iter_object_hashes()) == []
