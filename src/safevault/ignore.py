from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import pathspec


def default_patterns() -> list[str]:
    return [
        ".git/",
        "node_modules/",
        ".venv/",
        "venv/",
        "__pycache__/",
        "dist/",
        "build/",
        "target/",
        ".cache/",
        ".DS_Store",
        "*.pyc",
        "*.log",
        ".safevault/",
    ]


def build_pathspec(patterns: Sequence[str] | None = None) -> pathspec.PathSpec:
    return pathspec.PathSpec.from_lines("gitignore", patterns or default_patterns())


def rel_for_match(root: Path, path: Path) -> str:
    root_abs = Path(os.path.abspath(root))
    path_abs = Path(os.path.abspath(path))
    rel = path_abs.relative_to(root_abs)
    return rel.as_posix()


def is_ignored(root: Path, path: Path, spec: pathspec.PathSpec | None = None) -> bool:
    matcher = spec or build_pathspec()
    try:
        rel = rel_for_match(root, path)
    except ValueError:
        return True
    if rel in ("", "."):
        return False
    candidates = [rel]
    if not path.is_symlink() and path.is_dir() and not rel.endswith("/"):
        candidates.append(f"{rel}/")
    return any(matcher.match_file(candidate) for candidate in candidates)
