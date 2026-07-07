from __future__ import annotations

from pathlib import Path

from safevault.symlinks import (
    external_symlink_placeholder,
    is_external_symlink_placeholder_file,
    parse_external_symlink_placeholder,
    parse_symlink_payload,
    symlink_payload,
)


def test_external_symlink_placeholder_round_trips() -> None:
    payload = external_symlink_placeholder("/outside/target")
    assert parse_external_symlink_placeholder(payload) == "/outside/target"


def test_malformed_placeholder_bytes_return_none() -> None:
    assert parse_external_symlink_placeholder(b"") is None
    assert parse_external_symlink_placeholder(b"not-safevault") is None
    assert parse_external_symlink_placeholder(b"SAFEVAULT_EXTERNAL_SYMLINK\n") is None


def test_large_placeholder_detection_uses_bounded_read(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "large.txt"
    path.write_text("x", encoding="utf-8")
    read_sizes: list[int] = []

    class FakeReader:
        def __enter__(self) -> FakeReader:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            return b"x" * size

    def fake_open(self: Path, mode: str = "r", *args: object, **kwargs: object) -> FakeReader:
        assert self == path
        assert mode == "rb"
        _ = (args, kwargs)
        return FakeReader()

    monkeypatch.setattr(Path, "open", fake_open)
    assert is_external_symlink_placeholder_file(path, max_bytes=8) == (False, None)
    assert read_sizes == [9]


def test_symlink_payload_matches_snapshot_format() -> None:
    payload = symlink_payload("target.txt")
    assert payload == b"SYMLINK\ntarget.txt"
    assert parse_symlink_payload(payload) == "target.txt"
