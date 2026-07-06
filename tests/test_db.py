from __future__ import annotations

from safevault.db import connect, find_containing_root, get_or_create_root, get_root_by_path


def test_schema_initializes(sv_home) -> None:
    conn = connect()
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert {"roots", "files", "snapshots", "versions", "events", "sandboxes"} <= tables


def test_root_registration_and_idempotency(sv_home, project) -> None:
    conn = connect()
    try:
        first = get_or_create_root(conn, project, "coding")
        second = get_or_create_root(conn, project, "coding")
        root = get_root_by_path(conn, project)
    finally:
        conn.close()
    assert first == second
    assert root is not None
    assert root.profile == "coding"


def test_containing_root_lookup(sv_home, project) -> None:
    child = project / "src" / "app.py"
    child.parent.mkdir()
    child.write_text("print('x')", encoding="utf-8")
    conn = connect()
    try:
        root_id = get_or_create_root(conn, project, "coding")
        root = find_containing_root(conn, child)
    finally:
        conn.close()
    assert root is not None
    assert root.id == root_id
