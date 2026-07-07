from __future__ import annotations

import io
import json
import tarfile
from collections.abc import Callable

import pytest

from safevault.cli import app
from safevault.snapshot import create_snapshot

MISSING = object()


def test_import_dry_run_fully_validates_archive_without_writing(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    target = tmp_path / "imported-home"
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(target), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert not target.exists()


def test_import_confirm_creates_target_home_with_db_and_objects(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    target = tmp_path / "imported-home"
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(target), "--confirm"],
    )
    assert result.exit_code == 0
    assert (target / "vault.db").is_file()
    assert any((target / "objects").rglob("*"))


def test_import_confirm_accepts_empty_target_directory(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    target = tmp_path / "imported-home"
    target.mkdir()
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(target), "--confirm"],
    )
    assert result.exit_code == 0
    assert (target / "vault.db").is_file()


def test_import_overwrite_non_empty_target_requires_confirm_and_overwrite(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    refused = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(target), "--confirm"],
    )
    assert refused.exit_code != 0
    assert "not empty" in refused.output
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"

    result = runner.invoke(
        app,
        [
            "import",
            "--input",
            str(archive),
            "--target-home",
            str(target),
            "--confirm",
            "--overwrite",
        ],
    )
    assert result.exit_code == 0
    assert (target / "vault.db").is_file()
    assert not (target / "keep.txt").exists()


def test_import_without_confirm_remains_dry_run_and_does_not_modify_target(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "import",
            "--input",
            str(archive),
            "--target-home",
            str(target),
            "--dry-run",
            "--overwrite",
        ],
    )
    assert result.exit_code == 0
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (target / "vault.db").exists()


def test_import_refuses_path_traversal_member(runner, sv_home, tmp_path) -> None:
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as tar:
        _add_file(tar, "../evil.txt", b"bad")
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(tmp_path / "target")],
    )
    assert result.exit_code != 0
    assert "unsafe archive member" in result.output


def test_import_refuses_non_regular_archive_member(runner, sv_home, tmp_path) -> None:
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as tar:
        info = tarfile.TarInfo("manifest.json")
        info.type = tarfile.SYMTYPE
        info.linkname = "vault.db"
        tar.addfile(info)
        _add_file(tar, "vault.db", b"not sqlite")
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(tmp_path / "target")],
    )
    assert result.exit_code != 0
    assert "unsupported archive member type" in result.output


def test_import_dry_run_rejects_bad_manifest_schema(runner, sv_home, tmp_path) -> None:
    archive = _manual_archive(tmp_path, manifest={"schema_version": 999})
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(tmp_path / "target")],
    )
    assert result.exit_code != 0
    assert "manifest schema" in result.output


def test_import_dry_run_rejects_invalid_sqlite_db(runner, sv_home, tmp_path) -> None:
    archive = _manual_archive(tmp_path, manifest=_valid_empty_manifest())
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(tmp_path / "target")],
    )
    assert result.exit_code != 0
    assert "database integrity" in result.output


def test_import_dry_run_rejects_manifest_object_count_mismatch(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    bad = tmp_path / "bad-count.tar"

    def mutate(manifest: dict[str, object]) -> None:
        manifest["exported_object_count"] = int(manifest["exported_object_count"]) + 1

    _rewrite_manifest_archive(archive, bad, mutate)
    result = runner.invoke(
        app,
        ["import", "--input", str(bad), "--target-home", str(tmp_path / "target")],
    )
    assert result.exit_code != 0
    assert "exported_object_count" in result.output


def test_import_dry_run_rejects_corrupted_object(runner, sv_home, project, tmp_path) -> None:
    archive = _export_archive(runner, project, tmp_path)
    corrupt = tmp_path / "corrupt.tar"
    _rewrite_archive(
        archive,
        corrupt,
        lambda name, data: b"corrupt" if name.startswith("objects/") else data,
    )
    result = runner.invoke(
        app,
        ["import", "--input", str(corrupt), "--target-home", str(tmp_path / "target")],
    )
    assert result.exit_code != 0
    assert "corrupted" in result.output


def test_import_dry_run_rejects_duplicate_archive_members(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    duplicate = tmp_path / "duplicate.tar"
    with tarfile.open(archive) as src, tarfile.open(duplicate, "w") as dest:
        for member in src.getmembers():
            data = src.extractfile(member).read()
            _add_file(dest, member.name, data)
            if member.name == "manifest.json":
                _add_file(dest, member.name, data)
    result = runner.invoke(
        app,
        ["import", "--input", str(duplicate), "--target-home", str(tmp_path / "target")],
    )
    assert result.exit_code != 0
    assert "duplicate archive member" in result.output


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    [
        ("schema_version", MISSING, "manifest schema"),
        ("schema_version", 999, "manifest schema"),
        ("created_at", MISSING, "created_at"),
        ("created_at", "", "created_at"),
        ("safevault_version", MISSING, "safevault_version"),
        ("safevault_version", "", "safevault_version"),
        ("database", MISSING, "database"),
        ("database", "other.db", "database"),
        ("database_backup", MISSING, "database_backup"),
        ("database_backup", False, "database_backup"),
        ("referenced_object_count", MISSING, "referenced_object_count"),
        ("referenced_object_count", True, "referenced_object_count"),
        ("referenced_object_count", -1, "referenced_object_count"),
        ("exported_object_count", MISSING, "exported_object_count"),
        ("exported_object_count", True, "exported_object_count"),
        ("exported_object_count", -1, "exported_object_count"),
        ("included_orphans", MISSING, "included_orphans"),
        ("included_orphans", True, "included_orphans"),
        ("compression", MISSING, "compression"),
        ("compression", "zip", "compression"),
    ],
)
def test_import_requires_strict_manifest_fields(
    runner, sv_home, project, tmp_path, field: str, value: object, needle: str
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    bad = tmp_path / f"bad-{field}-{len(list(tmp_path.glob('bad-*.tar')))}.tar"

    def mutate(manifest: dict[str, object]) -> None:
        if value is MISSING:
            manifest.pop(field, None)
        else:
            manifest[field] = value

    _rewrite_manifest_archive(archive, bad, mutate)
    result = runner.invoke(
        app,
        ["import", "--input", str(bad), "--target-home", str(tmp_path / "target")],
    )
    assert result.exit_code != 0
    assert needle in result.output


def test_import_refuses_symlink_target(runner, sv_home, project, tmp_path) -> None:
    archive = _export_archive(runner, project, tmp_path)
    real = tmp_path / "real-target"
    real.mkdir()
    link = tmp_path / "link-target"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unsupported: {exc}")
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(link), "--dry-run"],
    )
    assert result.exit_code != 0
    assert "symlink" in result.output


def test_import_refuses_target_inside_current_safevault_home(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    result = runner.invoke(
        app,
        [
            "import",
            "--input",
            str(archive),
            "--target-home",
            str(sv_home / "imported"),
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "current SAFEVAULT_HOME" in result.output


def test_import_refuses_current_safevault_home_even_with_confirm_overwrite(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    result = runner.invoke(
        app,
        [
            "import",
            "--input",
            str(archive),
            "--target-home",
            str(sv_home),
            "--confirm",
            "--overwrite",
        ],
    )
    assert result.exit_code != 0
    assert "current SAFEVAULT_HOME" in result.output


def test_import_refuses_archive_inside_target_when_overwrite_requested(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    inside_archive = target / "export.tar"
    inside_archive.write_bytes(archive.read_bytes())
    result = runner.invoke(
        app,
        [
            "import",
            "--input",
            str(inside_archive),
            "--target-home",
            str(target),
            "--dry-run",
            "--overwrite",
        ],
    )
    assert result.exit_code != 0
    assert "containing the import archive" in result.output


def _export_archive(runner, project, tmp_path):
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = tmp_path / "export.tar"
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code == 0
    return output


def _valid_empty_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "created_at": "2026-07-07T00:00:00Z",
        "safevault_version": "0.1.0rc1",
        "database": "vault.db",
        "database_backup": True,
        "referenced_object_count": 0,
        "exported_object_count": 0,
        "included_orphans": False,
        "verified": True,
        "compression": "none",
    }


def _manual_archive(tmp_path, manifest: dict[str, object], db_payload: bytes = b"not sqlite"):
    archive = tmp_path / "manual.tar"
    with tarfile.open(archive, "w") as tar:
        _add_file(tar, "manifest.json", json.dumps(manifest).encode("utf-8"))
        _add_file(tar, "vault.db", db_payload)
    return archive


def _rewrite_manifest_archive(
    src_path, dest_path, mutate: Callable[[dict[str, object]], None]
) -> None:
    def transform(name: str, data: bytes) -> bytes:
        if name != "manifest.json":
            return data
        manifest = json.loads(data.decode("utf-8"))
        mutate(manifest)
        return json.dumps(manifest).encode("utf-8")

    _rewrite_archive(src_path, dest_path, transform)


def _rewrite_archive(
    src_path,
    dest_path,
    transform: Callable[[str, bytes], bytes],
) -> None:
    with tarfile.open(src_path) as src, tarfile.open(dest_path, "w") as dest:
        for member in src.getmembers():
            data = src.extractfile(member).read()
            _add_file(dest, member.name, transform(member.name, data), mtime=member.mtime)


def _add_file(
    archive: tarfile.TarFile, name: str, data: bytes, *, mtime: int | float | None = None
) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    if mtime is not None:
        info.mtime = mtime
    archive.addfile(info, io.BytesIO(data))
