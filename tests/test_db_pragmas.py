from __future__ import annotations

from safevault.db import connect


def test_db_pragmas_and_indexes(sv_home) -> None:
    conn = connect()
    try:
        assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) >= 5000
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) > 0
        indexes = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
    finally:
        conn.close()
    assert {
        "idx_files_root_rel",
        "idx_versions_file_id",
        "idx_versions_content_hash",
        "idx_events_root_type_time",
        "idx_snapshots_root_time",
    } <= indexes
