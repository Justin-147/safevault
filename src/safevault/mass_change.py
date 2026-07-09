from __future__ import annotations

from pathlib import Path

SUSPICIOUS_ENCRYPTION_EXTENSIONS = {
    ".crypted",
    ".crypt",
    ".enc",
    ".encrypted",
    ".locked",
    ".locky",
    ".ransom",
}


def has_suspicious_encryption_extension(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUSPICIOUS_ENCRYPTION_EXTENSIONS
