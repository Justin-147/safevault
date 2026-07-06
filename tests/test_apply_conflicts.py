from __future__ import annotations

import sys

from safevault.cli import app
from safevault.sandbox import apply_sandbox, create_sandbox


def test_modified_original_conflicts_and_preserves_user_version(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('sandbox')"],
    )
    file_path.write_text("user", encoding="utf-8")
    result = apply_sandbox(sandbox_id)
    assert result.conflicts == ["a.txt"]
    assert file_path.read_text(encoding="utf-8") == "user"


def test_deleted_original_conflicts_and_preserves_user_version(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project, [sys.executable, "-c", "from pathlib import Path; Path('a.txt').unlink()"]
    )
    file_path.write_text("user", encoding="utf-8")
    result = apply_sandbox(sandbox_id, allow_delete=True)
    assert result.conflicts == ["a.txt"]
    assert file_path.read_text(encoding="utf-8") == "user"


def test_created_file_conflicts_if_user_created_it_first(sv_home, project) -> None:
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('new.txt').write_text('sandbox')"],
    )
    (project / "new.txt").write_text("user", encoding="utf-8")
    result = apply_sandbox(sandbox_id)
    assert result.conflicts == ["new.txt"]
    assert (project / "new.txt").read_text(encoding="utf-8") == "user"


def test_non_conflicting_modified_file_applies(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('sandbox')"],
    )
    result = apply_sandbox(sandbox_id)
    assert not result.conflicts
    assert file_path.read_text(encoding="utf-8") == "sandbox"


def test_cli_output_mentions_conflict(runner, sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("old", encoding="utf-8")
    sandbox_id, _, _, _ = create_sandbox(
        project,
        [sys.executable, "-c", "from pathlib import Path; Path('a.txt').write_text('sandbox')"],
    )
    file_path.write_text("user", encoding="utf-8")
    result = runner.invoke(app, ["apply", sandbox_id])
    assert result.exit_code == 0
    assert "Conflicts" in result.output
