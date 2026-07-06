from __future__ import annotations

from safevault.ignore import is_ignored


def test_default_ignored_paths(project) -> None:
    ignored = [
        project / ".git",
        project / "node_modules",
        project / ".venv",
        project / "dist",
        project / "a.pyc",
        project / "debug.log",
    ]
    for path in ignored:
        if path.suffix:
            path.write_text("x", encoding="utf-8")
        else:
            path.mkdir()
        assert is_ignored(project, path)


def test_normal_source_file_not_ignored(project) -> None:
    path = project / "src" / "app.py"
    path.parent.mkdir()
    path.write_text("x", encoding="utf-8")
    assert not is_ignored(project, path)
