from __future__ import annotations

from dataclasses import dataclass

from safevault.db import connect
from safevault.object_store import is_valid_content_hash, object_path, verify_object
from safevault.paths import ensure_home_layout


@dataclass(frozen=True)
class VerifyResult:
    missing_objects: list[str]
    corrupted_objects: list[str]
    invalid_references: list[str]
    checked_objects: int
    deep: bool

    @property
    def healthy(self) -> bool:
        return (
            not self.missing_objects
            and not self.corrupted_objects
            and not self.invalid_references
        )


def run_verify(*, deep: bool = False) -> VerifyResult:
    ensure_home_layout()
    conn = connect()
    try:
        referenced = sorted(
            {
                str(row["content_hash"])
                for row in conn.execute(
                    "SELECT DISTINCT content_hash FROM versions WHERE content_hash IS NOT NULL"
                ).fetchall()
            }
        )
    finally:
        conn.close()

    missing: list[str] = []
    corrupted: list[str] = []
    invalid: list[str] = []
    for content_hash in referenced:
        if not is_valid_content_hash(content_hash):
            invalid.append(content_hash)
            continue
        path = object_path(content_hash)
        if not path.is_file():
            missing.append(content_hash)
        elif deep and not verify_object(content_hash):
            corrupted.append(content_hash)
    return VerifyResult(
        missing_objects=missing,
        corrupted_objects=corrupted,
        invalid_references=invalid,
        checked_objects=len(referenced),
        deep=deep,
    )
