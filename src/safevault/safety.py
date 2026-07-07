from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath

from safevault.config import PROTECTED_DELETE_NAMES
from safevault.errors import UnsafeOperationError
from safevault.filetypes import SafeFileKind, classify_no_follow
from safevault.ignore import build_pathspec


def safe_rel_path(rel_path: str) -> Path:
    """Convert POSIX-style diff metadata paths into safe local relative paths."""
    if not rel_path:
        raise UnsafeOperationError("empty relative path in diff")
    if "\x00" in rel_path:
        raise UnsafeOperationError(f"NUL byte in relative path: {rel_path!r}")
    if "\\" in rel_path:
        raise UnsafeOperationError(f"backslash path separators are not allowed: {rel_path}")
    if rel_path.startswith("/"):
        raise UnsafeOperationError(f"absolute path in diff: {rel_path}")

    windows_path = PureWindowsPath(rel_path)
    if windows_path.is_absolute() or windows_path.drive:
        raise UnsafeOperationError(f"drive-qualified path in diff: {rel_path}")

    parts = rel_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise UnsafeOperationError(f"unsafe relative path in diff: {rel_path}")

    posix_path = PurePosixPath(rel_path)
    if posix_path.is_absolute() or ".." in posix_path.parts:
        raise UnsafeOperationError(f"unsafe relative path in diff: {rel_path}")
    return Path(*posix_path.parts)


def is_within_directory(root: Path, candidate: Path) -> bool:
    root_resolved = root.resolve(strict=False)
    candidate_resolved = candidate.resolve(strict=False)
    return candidate_resolved == root_resolved or candidate_resolved.is_relative_to(root_resolved)


def is_protected_rel_path(rel_path: str) -> bool:
    try:
        safe_rel_path(rel_path)
    except UnsafeOperationError:
        return True

    parts = PurePosixPath(rel_path).parts
    if parts and parts[0] in PROTECTED_DELETE_NAMES:
        return True

    spec = build_pathspec()
    candidates = [rel_path]
    if not rel_path.endswith("/"):
        candidates.append(f"{rel_path}/")
    return any(spec.match_file(candidate) for candidate in candidates)


def validate_apply_target(original_root: Path, rel_path: str) -> Path:
    if is_protected_rel_path(rel_path):
        raise UnsafeOperationError(f"protected or ignored path in diff: {rel_path}")
    destination = original_root / safe_rel_path(rel_path)
    if not is_within_directory(original_root, destination):
        raise UnsafeOperationError(f"destination escapes original root: {rel_path}")
    return destination


def symlink_target_stays_within(root: Path, link_path: Path, link_target: str) -> bool:
    if "\x00" in link_target:
        return False
    root_resolved = root.resolve(strict=False)
    windows_target = PureWindowsPath(link_target)
    if os.path.isabs(link_target) or windows_target.is_absolute() or windows_target.drive:
        resolved_target = Path(link_target).resolve(strict=False)
    else:
        resolved_target = (link_path.parent / link_target).resolve(strict=False)
    return resolved_target == root_resolved or resolved_target.is_relative_to(root_resolved)


def source_kind_no_follow(path: Path) -> str | None:
    kind = classify_no_follow(path)
    if kind == SafeFileKind.SYMLINK:
        return "symlink"
    if kind == SafeFileKind.REGULAR:
        return "file"
    return None
