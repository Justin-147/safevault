from __future__ import annotations

import json
import tarfile

from safevault.cli import app
from safevault.paths import get_tmp_dir
from safevault.snapshot import create_snapshot


def test_export_creates_archive_with_db_objects_and_manifest(
    runner, sv_home, project, tmp_path
) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = tmp_path / "safevault-export.tar"
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code == 0
    with tarfile.open(output) as archive:
        names = archive.getnames()
        assert "vault.db" in names
        assert "manifest.json" in names
        assert any(name.startswith("objects/") for name in names)
        manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
    assert manifest["object_count"] == 1
    assert manifest["database"] == "vault.db"


def test_export_excludes_tmp_and_partial_files(runner, sv_home, project, tmp_path) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    tmp_file = get_tmp_dir() / "leftover.partial"
    tmp_file.write_text("partial", encoding="utf-8")
    output = tmp_path / "safevault-export.tar.gz"
    result = runner.invoke(app, ["export", "--output", str(output), "--gzip"])
    assert result.exit_code == 0
    with tarfile.open(output, "r:gz") as archive:
        assert "tmp/leftover.partial" not in archive.getnames()


def test_export_refuses_output_inside_vault_home(runner, sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = sv_home / "export.tar"
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code != 0
    assert "inside SAFEVAULT_HOME" in result.output


def test_export_allows_output_inside_vault_home_with_flag(runner, sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = sv_home / "export.tar"
    result = runner.invoke(
        app, ["export", "--output", str(output), "--allow-inside-vault"]
    )
    assert result.exit_code == 0
    assert output.exists()
