from __future__ import annotations

from safevault.db import connect
from safevault.mass_change import has_suspicious_encryption_extension
from safevault.snapshot import create_snapshot


def test_suspicious_encryption_extension_detection() -> None:
    assert has_suspicious_encryption_extension("report.docx.locked")
    assert has_suspicious_encryption_extension("photo.jpg.ENCRYPTED")
    assert has_suspicious_encryption_extension("archive.crypt")
    assert not has_suspicious_encryption_extension("normal.docx")


def test_emergency_mass_change_restore_point_is_important(sv_home, project) -> None:
    (project / "locked.docx").write_text("content", encoding="utf-8")

    create_snapshot(project, reason="emergency-mass-change")

    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT rp.*
            FROM restore_points rp
            JOIN snapshots s ON s.id = rp.snapshot_id
            WHERE s.reason = 'emergency-mass-change'
            """
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["important"] == 1
