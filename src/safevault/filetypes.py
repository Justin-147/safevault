from __future__ import annotations

import stat
from enum import StrEnum
from pathlib import Path


class SafeFileKind(StrEnum):
    REGULAR = "file"
    SYMLINK = "symlink"
    DIRECTORY = "directory"
    OTHER = "other"


def classify_no_follow(path: Path) -> SafeFileKind:
    try:
        stat_result = path.lstat()
    except OSError:
        return SafeFileKind.OTHER
    if stat.S_ISREG(stat_result.st_mode):
        return SafeFileKind.REGULAR
    if stat.S_ISLNK(stat_result.st_mode):
        return SafeFileKind.SYMLINK
    if stat.S_ISDIR(stat_result.st_mode):
        return SafeFileKind.DIRECTORY
    return SafeFileKind.OTHER


def is_regular_file_no_follow(path: Path) -> bool:
    return classify_no_follow(path) == SafeFileKind.REGULAR


def is_symlink_no_follow(path: Path) -> bool:
    return classify_no_follow(path) == SafeFileKind.SYMLINK
