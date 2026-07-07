from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from safevault.hashing import hash_bytes, hash_file, hash_symlink_target
from safevault.ignore import build_pathspec, is_ignored
from safevault.models import DiffEntry, DiffResult
from safevault.safety import symlink_target_stays_within
from safevault.snapshot import relative_path
from safevault.symlinks import (
    external_symlink_placeholder,
    is_external_symlink_placeholder_file,
    symlink_payload,
)

ManifestEntry = dict[str, object]


def _size(entry: ManifestEntry) -> int:
    return cast(int, entry["size"])


def _symlink_hash(path: Path) -> tuple[str, int]:
    target = os.readlink(path)
    return hash_symlink_target(target), len(symlink_payload(target))


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
                        target = os.readlink(path)
                        digest, size = _symlink_hash(path)
                        manifest[relative_path(root, path)] = {
                            "file_kind": "symlink",
                            "hash": digest,
                            "size": size,
                            "symlink_target": target,
                            "placeholder_target": None,
                            "symlink_external": not symlink_target_stays_within(
                                root, path, target
                            ),
                        }
                    elif entry.is_dir(follow_symlinks=False):
                        stack.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        stat_result = path.stat()
                        is_placeholder, placeholder_target = (
                            is_external_symlink_placeholder_file(path)
                        )
                        if is_placeholder and placeholder_target is not None:
                            payload = external_symlink_placeholder(placeholder_target)
                            manifest[relative_path(root, path)] = {
                                "file_kind": "external_symlink_placeholder",
                                "hash": hash_bytes(payload),
                                "size": len(payload),
                                "symlink_target": None,
                                "placeholder_target": placeholder_target,
                            }
                        else:
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
            if _unchanged_external_symlink_placeholder(old_entry, new_entry):
                continue
            entries.append(
                DiffEntry(
                    rel_path=rel_path,
                    change_type="modified",
                    file_kind=str(new_entry["file_kind"]),
                    old_file_kind=str(old_entry["file_kind"]),
                    old_hash=str(old_entry["hash"]),
                    new_hash=str(new_entry["hash"]),
                    old_size=_size(old_entry),
                    new_size=_size(new_entry),
                )
            )
    return DiffResult(
        entries,
        original_root=str(original.expanduser().resolve()),
        sandbox_root=str(candidate.expanduser().resolve()),
    )


def _unchanged_external_symlink_placeholder(
    old_entry: ManifestEntry, new_entry: ManifestEntry
) -> bool:
    return (
        old_entry.get("file_kind") == "symlink"
        and old_entry.get("symlink_external") is True
        and new_entry.get("file_kind") == "external_symlink_placeholder"
        and old_entry.get("symlink_target") == new_entry.get("placeholder_target")
    )
