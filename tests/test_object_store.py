from __future__ import annotations

from safevault.hashing import hash_bytes
from safevault.object_store import (
    iter_object_hashes,
    object_path,
    read_object,
    store_bytes,
    store_file,
)
from safevault.paths import get_objects_dir


def test_same_content_has_same_hash() -> None:
    digest = hash_bytes(b"same")
    assert digest == hash_bytes(b"same")
    assert len(digest) == 64


def test_same_content_stored_once_and_read_back(sv_home, tmp_path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"payload")
    first = store_file(path)
    second = store_bytes(b"payload")
    assert first == second
    assert object_path(first).is_file()
    assert len(list(iter_object_hashes())) == 1
    assert read_object(first) == b"payload"


def test_object_path_uses_hash_prefix_layout(sv_home) -> None:
    digest = store_bytes(b"x")
    path = object_path(digest)
    assert path.parts[-3:] == (digest[:2], digest[2:4], digest)


def test_partial_temp_files_are_not_valid_objects(sv_home) -> None:
    objects = get_objects_dir()
    bad = objects / "aa" / "bb"
    bad.mkdir(parents=True)
    (bad / ("a" * 64 + ".tmp")).write_text("x", encoding="utf-8")
    (bad / ("b" * 64 + ".partial")).write_text("x", encoding="utf-8")
    assert list(iter_object_hashes()) == []


def test_store_bytes_repairs_corrupted_existing_object(sv_home) -> None:
    digest = store_bytes(b"repair me")
    object_path(digest).write_bytes(b"corrupt")
    assert store_bytes(b"repair me") == digest
    assert read_object(digest) == b"repair me"


def test_store_file_repairs_corrupted_existing_object(sv_home, tmp_path) -> None:
    path = tmp_path / "payload.txt"
    path.write_bytes(b"file payload")
    digest = store_file(path)
    object_path(digest).write_bytes(b"corrupt")
    assert store_file(path) == digest
    assert read_object(digest) == b"file payload"


def test_corrupted_existing_object_is_not_reused_silently(sv_home) -> None:
    digest = store_bytes(b"payload")
    object_path(digest).write_bytes(b"corrupt")
    store_bytes(b"payload")
    assert object_path(digest).read_bytes() == b"payload"
