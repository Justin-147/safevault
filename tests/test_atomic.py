from __future__ import annotations

from safevault.atomic import atomic_copy_file


def test_atomic_copy_file_writes_content_and_cleans_temps(tmp_path) -> None:
    src = tmp_path / "src.bin"
    dest = tmp_path / "dest.bin"
    src.write_bytes(b"payload" * 1000)
    atomic_copy_file(src, dest)
    assert dest.read_bytes() == src.read_bytes()
    assert not list(tmp_path.glob(".dest.bin.*.tmp"))
