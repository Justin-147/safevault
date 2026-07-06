from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from safevault.hashing import hash_bytes, hash_file
from safevault.ignore import build_pathspec, is_ignored
from safevault.models import DiffEntry, DiffResult
from safevault.snapshot import relative_path

ManifestEntry = dict[str, object]


def _size(entry: ManifestEntry) -> int:
    return cast(int, entry["size"])


def _symlink_hash(path: Path) -> tuple[str, int]:
    payload = f"SYMLINK\n{os.readlink(path)}".encode("utf-8", "surrogateescape")
    return hash_bytes(payload), len(payload)


def build_manifest(root: Path) -> dict[str, ManifestEntry]:
    root = root.expanduser().resolve()
    spec = build_pathspec()
    manifest: dict[str, ManifestEntry] = {}
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if is_ignored(root, path, spec):
                        continue
                    if entry.is_symlink():
                        digest, size = _symlink_hash(path)
                        manifest[relative_path(root, path)] = {
                            "file_kind": "symlink",
                            "hash": digest,
                            "size": size,
                        }
                    elif entry.is_dir(follow_symlinks=False):
                        stack.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        stat_result = path.stat()
                        manifest[relative_path(root, path)] = {
                            "file_kind": "file",
                            "hash": hash_file(path),
                            "size": int(stat_result.st_size),
                        }
        except OSError:
            continue
    return manifest


def diff_dirs(original: Path, candidate: Path) -> DiffResult:
    old = build_manifest(original)
    new = build_manifest(candidate)
    entries: list[DiffEntry] = []
    for rel_path in sorted(set(old) | set(new)):
        old_entry = old.get(rel_path)
        new_entry = new.get(rel_path)
        if old_entry is None and new_entry is not None:
            entries.append(
                DiffEntry(
                    rel_path=rel_path,
                    change_type="created",
                    file_kind=str(new_entry["file_kind"]),
                    new_hash=str(new_entry["hash"]),
                    new_size=_size(new_entry),
                )
            )
        elif old_entry is not None and new_entry is None:
            entries.append(
                DiffEntry(
                    rel_path=rel_path,
                    change_type="deleted",
                    file_kind=str(old_entry["file_kind"]),
                    old_hash=str(old_entry["hash"]),
                    old_size=_size(old_entry),
                )
            )
        elif old_entry is not None and new_entry is not None and (
            old_entry["hash"] != new_entry["hash"]
            or old_entry["file_kind"] != new_entry["file_kind"]
        ):
            entries.append(
                DiffEntry(
                    rel_path=rel_path,
                    change_type="modified",
                    file_kind=str(new_entry["file_kind"]),
                    old_hash=str(old_entry["hash"]),
                    new_hash=str(new_entry["hash"]),
                    old_size=_size(old_entry),
                    new_size=_size(new_entry),
                )
            )
    return DiffResult(entries)
