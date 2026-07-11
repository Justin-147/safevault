from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from safevault.cli import app
from safevault.errors import SafeVaultError
from safevault.paths import (
    ensure_home_layout,
    get_safevault_home,
    set_safevault_home_location,
)
from safevault.restore import restore_file
from safevault.snapshot import create_snapshot
from safevault.storage import (
    MIGRATION_CONFIRMATION,
    analyze_storage,
    get_storage_status,
    migrate_storage,
    set_storage_budget,
    validate_storage_destination,
)


@pytest.fixture()
def movable_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("SAFEVAULT_HOME", raising=False)
    home = tmp_path / "legacy-home"
    monkeypatch.setenv("SAFEVAULT_DEFAULT_HOME", str(home))
    monkeypatch.setenv("SAFEVAULT_LOCATION_FILE", str(tmp_path / "location.txt"))
    ensure_home_layout()
    return home


def test_storage_location_pointer_is_backward_compatible(
    movable_home: Path, tmp_path: Path
) -> None:
    assert get_safevault_home() == movable_home.resolve()

    selected = set_safevault_home_location(tmp_path / "data-drive" / "SafeVaultData")

    assert get_safevault_home() == selected


def test_storage_location_pointer_supports_unicode_paths(
    movable_home: Path, tmp_path: Path
) -> None:
    selected = set_safevault_home_location(tmp_path / "数据盘" / "恢复文件")

    assert get_safevault_home() == selected


def test_storage_migration_preserves_restore_and_can_remove_source(
    movable_home: Path, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target_file = project / "recover-me.txt"
    target_file.write_text("protected", encoding="utf-8")
    create_snapshot(project)
    destination = tmp_path / "data-drive" / "SafeVaultData"

    result = migrate_storage(
        destination,
        remove_source=True,
        confirmation=MIGRATION_CONFIRMATION,
    )

    assert result.source_removed is True
    assert movable_home.exists() is False
    assert get_safevault_home() == destination.resolve()
    assert (destination / "vault.db").is_file()
    assert any((destination / "objects").rglob("*"))
    target_file.unlink()
    restored = restore_file(target_file, latest=True)
    assert restored.read_text(encoding="utf-8") == "protected"


def test_storage_migration_requires_confirmation_before_source_removal(
    movable_home: Path, tmp_path: Path
) -> None:
    with pytest.raises(SafeVaultError, match=MIGRATION_CONFIRMATION):
        migrate_storage(tmp_path / "new-home", remove_source=True)

    assert movable_home.is_dir()


def test_storage_migration_rejects_destination_without_free_space(
    movable_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "safevault.storage.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=100, used=100, free=0),
    )

    with pytest.raises(SafeVaultError, match="enough free space"):
        migrate_storage(tmp_path / "new-home")

    assert movable_home.is_dir()


def test_storage_destination_must_not_overlap_protected_root(
    movable_home: Path, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("a", encoding="utf-8")
    create_snapshot(project)

    with pytest.raises(SafeVaultError, match="protected root"):
        validate_storage_destination(project / "SafeVaultData")


def test_storage_analysis_and_budget_report_minimum_recoverable_size(
    movable_home: Path, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "large.bin").write_bytes(b"x" * 4096)
    create_snapshot(project)
    set_storage_budget(10)

    analysis = analyze_storage()
    status = get_storage_status()

    assert analysis.minimum_recoverable_bytes == 4096
    assert analysis.root_usage[0].minimum_bytes == 4096
    assert analysis.largest_files[0].rel_path == "large.bin"
    assert status.budget_gb == 10


def test_storage_status_cli_reports_selected_location(
    runner, movable_home: Path
) -> None:
    result = runner.invoke(app, ["storage", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["home"] == str(movable_home.resolve())
    assert data["budget_gb"] == 10
