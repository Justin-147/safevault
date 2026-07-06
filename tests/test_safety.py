from __future__ import annotations

from pathlib import Path

import pytest

from safevault.errors import UnsafeOperationError
from safevault.safety import (
    is_protected_rel_path,
    safe_rel_path,
    symlink_target_stays_within,
)


@pytest.mark.parametrize(
    "rel_path",
    ["../outside.txt", "/tmp/outside.txt", "C:\\Users\\x", "C:/Users/x", "a//b"],
)
def test_unsafe_relative_paths_are_rejected(rel_path: str) -> None:
    with pytest.raises(UnsafeOperationError):
        safe_rel_path(rel_path)


@pytest.mark.parametrize(
    "rel_path",
    [".git/config", ".safevault/vault.db", "node_modules/pkg/index.js"],
)
def test_protected_paths_are_detected(rel_path: str) -> None:
    assert is_protected_rel_path(rel_path)


def test_normal_path_is_accepted() -> None:
    assert safe_rel_path("src/app.py") == Path("src") / "app.py"
    assert not is_protected_rel_path("src/app.py")


def test_internal_relative_symlink_target_is_accepted(tmp_path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    link = root / "link"
    assert symlink_target_stays_within(root, link, "src/app.py")


def test_external_absolute_symlink_target_is_rejected(tmp_path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "secret"
    root.mkdir()
    outside.write_text("secret", encoding="utf-8")
    assert not symlink_target_stays_within(root, root / "link", str(outside))


def test_external_relative_symlink_target_is_rejected(tmp_path) -> None:
    root = tmp_path / "project"
    nested = root / "nested"
    nested.mkdir(parents=True)
    assert not symlink_target_stays_within(root, nested / "link", "../../secret")
