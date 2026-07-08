from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from safevault.config import VALID_PROFILES, load_config
from safevault.db import (
    connect,
    get_or_create_root,
    get_root_by_path,
    list_protection_policies,
    set_protection_policy_enabled,
    utc_now_iso,
)
from safevault.durations import parse_duration
from safevault.errors import RootNotFoundError, SafeVaultError
from safevault.models import ProtectionPolicy
from safevault.paths import get_safevault_home


@dataclass(frozen=True)
class AutoProtectCandidate:
    path: str
    profile: str
    recommended: bool
    reason: str


def register_protected_root(
    path: Path,
    profile: str,
    *,
    source: str,
    fail_if_exists: bool = False,
) -> int:
    root_path = validate_protection_path(path)
    if profile not in VALID_PROFILES:
        raise SafeVaultError(
            "profile must be one of: " + ", ".join(sorted(VALID_PROFILES))
        )
    conn = connect()
    try:
        existing = get_root_by_path(conn, root_path)
        if existing is not None and fail_if_exists:
            raise SafeVaultError(f"root is already protected: {root_path}")
        root_id = get_or_create_root(conn, root_path, profile)
        conn.commit()
        return root_id
    finally:
        conn.close()


def add_protected_root(path: Path, profile: str) -> int:
    return register_protected_root(
        path,
        profile,
        source="protect-add",
        fail_if_exists=True,
    )


def remove_protected_root(path: Path) -> ProtectionPolicy:
    root_path = path.expanduser().resolve(strict=False)
    conn = connect()
    try:
        root = get_root_by_path(conn, root_path)
        if root is None:
            raise RootNotFoundError(f"path is not a protected root: {root_path}")
        policies = {policy.root_id: policy for policy in list_protection_policies(conn)}
        policy = policies.get(root.id)
        if policy is None:
            raise SafeVaultError(f"protection policy missing for root: {root_path}")
        set_protection_policy_enabled(conn, root.id, enabled=False)
        conn.commit()
        return policy
    finally:
        conn.close()


def list_protection() -> list[ProtectionPolicy]:
    conn = connect()
    try:
        return list_protection_policies(conn)
    finally:
        conn.close()


def list_enabled_policies() -> list[ProtectionPolicy]:
    return list_watchable_policies()


def list_watchable_policies(now: datetime | None = None) -> list[ProtectionPolicy]:
    current = datetime.now(UTC) if now is None else now
    return [policy for policy in list_protection() if policy_is_watchable(policy, current)]


def policy_is_watchable(policy: ProtectionPolicy, now: datetime | None = None) -> bool:
    current = datetime.now(UTC) if now is None else now
    return (
        policy.enabled
        and policy.watch_enabled
        and (policy.paused_until is None or _parse_iso(policy.paused_until) <= current)
        and root_safety_issue(Path(policy.root_path)) is None
    )


def pause_protected_root(path: Path, duration: str) -> ProtectionPolicy:
    root_path = path.expanduser().resolve(strict=False)
    paused_until = (datetime.now(UTC) + parse_duration(duration)).isoformat(
        timespec="microseconds"
    )
    conn = connect()
    try:
        root = get_root_by_path(conn, root_path)
        if root is None:
            raise RootNotFoundError(f"path is not a protected root: {root_path}")
        policy = _policy_for_root(conn, root.id)
        conn.execute(
            """
            UPDATE protection_policies
            SET paused_until = ?, updated_at = ?
            WHERE root_id = ?
            """,
            (paused_until, utc_now_iso(), root.id),
        )
        conn.commit()
        return policy
    finally:
        conn.close()


def resume_protected_root(path: Path) -> ProtectionPolicy:
    root_path = path.expanduser().resolve(strict=False)
    conn = connect()
    try:
        root = get_root_by_path(conn, root_path)
        if root is None:
            raise RootNotFoundError(f"path is not a protected root: {root_path}")
        policy = _policy_for_root(conn, root.id)
        conn.execute(
            """
            UPDATE protection_policies
            SET watch_enabled = 1, paused_until = NULL, updated_at = ?
            WHERE root_id = ?
            """,
            (utc_now_iso(), root.id),
        )
        conn.commit()
        return policy
    finally:
        conn.close()


def validate_protection_path(path: Path) -> Path:
    root_path = path.expanduser().resolve(strict=False)
    issue = root_safety_issue(root_path)
    if issue is not None:
        raise SafeVaultError(issue)
    return root_path


def root_safety_issue(path: Path) -> str | None:
    root_path = path.expanduser().resolve(strict=False)
    if not root_path.exists():
        return f"path does not exist: {root_path}"
    if not root_path.is_dir():
        return f"path is not a directory: {root_path}"
    if _is_filesystem_root(root_path):
        return "cannot protect a filesystem root"
    if issue := _safevault_home_issue(root_path):
        return issue
    if issue := _backup_target_issue(root_path):
        return issue
    return None


def auto_detect_candidates() -> list[AutoProtectCandidate]:
    candidates: list[tuple[Path, str, bool, str]] = []
    home = Path.home()
    userprofile = Path(os.environ.get("USERPROFILE", str(home))).expanduser()
    candidates.extend(
        [
            (userprofile / "Desktop", "desktop", True, "Desktop"),
            (userprofile / "Documents", "documents", True, "Documents"),
            (userprofile / "Downloads", "downloads", False, "Downloads is optional"),
            (Path("D:/CodexWork"), "coding", True, "Codex workspace"),
            (userprofile / "source", "coding", True, "source projects"),
            (userprofile / "Projects", "coding", True, "Projects"),
        ]
    )
    detected: list[AutoProtectCandidate] = []
    seen: set[str] = set()
    for path, profile, recommended, reason in candidates:
        try:
            resolved = path.expanduser().resolve(strict=False)
        except OSError:
            continue
        key = _casefold_path(resolved)
        if key in seen or not resolved.is_dir():
            continue
        seen.add(key)
        try:
            validate_protection_path(resolved)
        except SafeVaultError:
            continue
        detected.append(
            AutoProtectCandidate(
                path=str(resolved),
                profile=profile,
                recommended=recommended,
                reason=reason,
            )
        )
    return detected


def _reject_safevault_home(root_path: Path) -> None:
    issue = _safevault_home_issue(root_path)
    if issue is not None:
        raise SafeVaultError(issue)


def _reject_backup_target(root_path: Path) -> None:
    issue = _backup_target_issue(root_path)
    if issue is not None:
        raise SafeVaultError(issue)


def _safevault_home_issue(root_path: Path) -> str | None:
    home = get_safevault_home().resolve(strict=False)
    if root_path == home or root_path.is_relative_to(home) or home.is_relative_to(root_path):
        return "cannot protect SAFEVAULT_HOME or a directory containing it"
    return None


def _backup_target_issue(root_path: Path) -> str | None:
    target = load_config().backup.target
    if not target:
        return None
    backup_path = Path(target).expanduser().resolve(strict=False)
    if (
        root_path == backup_path
        or root_path.is_relative_to(backup_path)
        or backup_path.is_relative_to(root_path)
    ):
        return "cannot protect the configured backup target"
    return None


def _is_filesystem_root(path: Path) -> bool:
    return path == path.parent


def _casefold_path(path: Path) -> str:
    return str(path).casefold() if os.name == "nt" else str(path)


def _policy_for_root(conn, root_id: int) -> ProtectionPolicy:
    policies = {policy.root_id: policy for policy in list_protection_policies(conn)}
    policy = policies.get(root_id)
    if policy is None:
        raise SafeVaultError(f"protection policy missing for root id: {root_id}")
    return policy


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
