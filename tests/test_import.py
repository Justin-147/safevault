from __future__ import annotations

import io
import json
import tarfile

from safevault.cli import app
from safevault.snapshot import create_snapshot


def test_import_dry_run_reports_archive_without_writing(runner, sv_home, project, tmp_path) -> None:
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


def test_import_refuses_path_traversal_member(runner, sv_home, tmp_path) -> None:
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as tar:
        payload = b"bad"
        info = tarfile.TarInfo("../evil.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
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
        payload = b"not sqlite"
        info = tarfile.TarInfo("vault.db")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(tmp_path / "target")],
    )
    assert result.exit_code != 0
    assert "unsupported archive member type" in result.output


def test_import_refuses_bad_manifest_schema(runner, sv_home, tmp_path) -> None:
    archive = _manual_archive(tmp_path, manifest={"schema_version": 999})
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(tmp_path / "target"), "--confirm"],
    )
    assert result.exit_code != 0
    assert "manifest schema" in result.output


def test_import_refuses_manifest_object_count_mismatch(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    bad = tmp_path / "bad-count.tar"
    with tarfile.open(archive) as src, tarfile.open(bad, "w") as dest:
        for member in src.getmembers():
            data = src.extractfile(member).read()
            if member.name == "manifest.json":
                manifest = json.loads(data.decode("utf-8"))
                manifest["object_count"] += 1
                data = json.dumps(manifest).encode("utf-8")
            info = tarfile.TarInfo(member.name)
            info.size = len(data)
            info.mtime = member.mtime
            dest.addfile(info, io.BytesIO(data))
    result = runner.invoke(
        app,
        ["import", "--input", str(bad), "--target-home", str(tmp_path / "target"), "--confirm"],
    )
    assert result.exit_code != 0
    assert "object_count" in result.output


def test_import_refuses_corrupted_object(runner, sv_home, project, tmp_path) -> None:
    archive = _export_archive(runner, project, tmp_path)
    corrupt = tmp_path / "corrupt.tar"
    with tarfile.open(archive) as src, tarfile.open(corrupt, "w") as dest:
        for member in src.getmembers():
            data = src.extractfile(member).read() if member.isfile() else b""
            if member.name.startswith("objects/"):
                data = b"corrupt"
                member.size = len(data)
            dest.addfile(member, io.BytesIO(data))
    result = runner.invoke(
        app,
        ["import", "--input", str(corrupt), "--target-home", str(tmp_path / "target"), "--confirm"],
    )
    assert result.exit_code != 0
    assert "corrupted" in result.output


def test_import_refuses_non_empty_target_without_overwrite(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(target), "--confirm"],
    )
    assert result.exit_code != 0
    assert "not empty" in result.output


def test_import_refuses_current_safevault_home_without_explicit_overwrite(
    runner, sv_home, project, tmp_path
) -> None:
    archive = _export_archive(runner, project, tmp_path)
    result = runner.invoke(
        app,
        ["import", "--input", str(archive), "--target-home", str(sv_home), "--confirm"],
    )
    assert result.exit_code != 0
    assert "current SAFEVAULT_HOME" in result.output


def _export_archive(runner, project, tmp_path):
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = tmp_path / "export.tar"
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code == 0
    return output


def _manual_archive(tmp_path, manifest: dict[str, object]):
    archive = tmp_path / "manual.tar"
    with tarfile.open(archive, "w") as tar:
        payload = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
        db_payload = b"not sqlite"
        info = tarfile.TarInfo("vault.db")
        info.size = len(db_payload)
        tar.addfile(info, io.BytesIO(db_payload))
    return archive
