from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from safevault.atomic import atomic_write_bytes
from safevault.errors import SafeVaultError
from safevault.paths import ensure_home_layout, get_safevault_home

DEFAULT_PROFILE = "coding"
VALID_PROFILES = {"coding", "documents", "downloads", "desktop"}

PROTECTED_DELETE_NAMES = {
    ".git",
    ".safevault",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
}

BackupSchedule = Literal["manual", "daily", "weekly"]


@dataclass(frozen=True)
class AppConfig:
    onboarding_completed: bool = False
    advanced_mode: bool = False
    language: str = "zh-CN"


@dataclass(frozen=True)
class DaemonConfig:
    enabled: bool = True
    heartbeat_interval_seconds: int = 30
    policy_refresh_seconds: int = 10
    watch_debounce_seconds: int = 3
    batch_window_seconds: int = 20
    bulk_delete_threshold: int = 20
    bulk_delete_window_seconds: int = 30
    hourly_snapshot_enabled: bool = True
    daily_snapshot_enabled: bool = True
    idle_verify_enabled: bool = True
    idle_verify_after_minutes: int = 15


@dataclass(frozen=True)
class ProtectionConfig:
    auto_protect_desktop: bool = True
    auto_protect_documents: bool = True
    auto_protect_downloads: bool = False
    auto_protect_dev_projects: bool = True


@dataclass(frozen=True)
class BackupConfig:
    enabled: bool = False
    target: str | None = None
    schedule: BackupSchedule = "manual"
    time: str = "21:00"
    gzip: bool = True
    overwrite_latest: bool = True
    keep_last: int = 7
    skip_verify: bool = False


@dataclass(frozen=True)
class RetentionConfig:
    max_vault_size_gb: int = 10
    keep_days: int = 7
    conservative_prune_only: bool = True
    auto_cleanup_enabled: bool = False
    last_cleanup_at: str | None = None
    last_cleanup_status: str = "never"
    last_cleanup_deleted_versions: int = 0
    last_cleanup_reclaimed_bytes: int = 0
    last_cleanup_error: str | None = None


@dataclass(frozen=True)
class UiConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    show_advanced_actions: bool = False


@dataclass(frozen=True)
class SafeVaultConfig:
    app: AppConfig = AppConfig()
    daemon: DaemonConfig = DaemonConfig()
    protection: ProtectionConfig = ProtectionConfig()
    backup: BackupConfig = BackupConfig()
    retention: RetentionConfig = RetentionConfig()
    ui: UiConfig = UiConfig()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SafeVaultConfig:
        app = data.get("app", {})
        daemon = data.get("daemon", {})
        protection = data.get("protection", {})
        backup = data.get("backup", {})
        retention = data.get("retention", {})
        ui = data.get("ui", {})
        retention_keep_days: object = retention.get("keep_days", 7)
        if (
            "auto_cleanup_enabled" not in retention
            and str(retention_keep_days) == "90"
        ):
            retention_keep_days = 7
        return cls(
            app=AppConfig(
                onboarding_completed=bool(app.get("onboarding_completed", False)),
                advanced_mode=bool(app.get("advanced_mode", False)),
                language=str(app.get("language", "zh-CN")),
            ),
            daemon=DaemonConfig(
                enabled=bool(daemon.get("enabled", True)),
                heartbeat_interval_seconds=_positive_int(
                    daemon.get("heartbeat_interval_seconds", 30),
                    "daemon.heartbeat_interval_seconds",
                ),
                policy_refresh_seconds=_positive_int(
                    daemon.get("policy_refresh_seconds", 10),
                    "daemon.policy_refresh_seconds",
                ),
                watch_debounce_seconds=_positive_int(
                    daemon.get("watch_debounce_seconds", 3),
                    "daemon.watch_debounce_seconds",
                ),
                batch_window_seconds=_positive_int(
                    daemon.get("batch_window_seconds", 20),
                    "daemon.batch_window_seconds",
                ),
                bulk_delete_threshold=_positive_int(
                    daemon.get("bulk_delete_threshold", 20),
                    "daemon.bulk_delete_threshold",
                ),
                bulk_delete_window_seconds=_positive_int(
                    daemon.get("bulk_delete_window_seconds", 30),
                    "daemon.bulk_delete_window_seconds",
                ),
                hourly_snapshot_enabled=bool(daemon.get("hourly_snapshot_enabled", True)),
                daily_snapshot_enabled=bool(daemon.get("daily_snapshot_enabled", True)),
                idle_verify_enabled=bool(daemon.get("idle_verify_enabled", True)),
                idle_verify_after_minutes=_positive_int(
                    daemon.get("idle_verify_after_minutes", 15),
                    "daemon.idle_verify_after_minutes",
                ),
            ),
            protection=ProtectionConfig(
                auto_protect_desktop=bool(protection.get("auto_protect_desktop", True)),
                auto_protect_documents=bool(protection.get("auto_protect_documents", True)),
                auto_protect_downloads=bool(protection.get("auto_protect_downloads", False)),
                auto_protect_dev_projects=bool(
                    protection.get("auto_protect_dev_projects", True)
                ),
            ),
            backup=BackupConfig(
                enabled=bool(backup.get("enabled", False)),
                target=_normalize_optional_path(backup.get("target")),
                schedule=_backup_schedule(backup.get("schedule", "manual")),
                time=_backup_time(backup.get("time", "21:00")),
                gzip=bool(backup.get("gzip", True)),
                overwrite_latest=bool(backup.get("overwrite_latest", True)),
                keep_last=_positive_int(backup.get("keep_last", 7), "backup.keep_last"),
                skip_verify=bool(backup.get("skip_verify", False)),
            ),
            retention=RetentionConfig(
                max_vault_size_gb=_positive_int(
                    retention.get("max_vault_size_gb", 10),
                    "retention.max_vault_size_gb",
                ),
                keep_days=_positive_int(retention_keep_days, "retention.keep_days"),
                conservative_prune_only=bool(
                    retention.get("conservative_prune_only", True)
                ),
                auto_cleanup_enabled=bool(retention.get("auto_cleanup_enabled", False)),
                last_cleanup_at=_optional_text(retention.get("last_cleanup_at")),
                last_cleanup_status=str(retention.get("last_cleanup_status", "never")),
                last_cleanup_deleted_versions=_nonnegative_int(
                    retention.get("last_cleanup_deleted_versions", 0),
                    "retention.last_cleanup_deleted_versions",
                ),
                last_cleanup_reclaimed_bytes=_nonnegative_int(
                    retention.get("last_cleanup_reclaimed_bytes", 0),
                    "retention.last_cleanup_reclaimed_bytes",
                ),
                last_cleanup_error=_optional_text(retention.get("last_cleanup_error")),
            ),
            ui=UiConfig(
                host=str(ui.get("host", "127.0.0.1")),
                port=_port_int(ui.get("port", 8765)),
                show_advanced_actions=bool(ui.get("show_advanced_actions", False)),
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "app": {
                "onboarding_completed": self.app.onboarding_completed,
                "advanced_mode": self.app.advanced_mode,
                "language": self.app.language,
            },
            "daemon": {
                "enabled": self.daemon.enabled,
                "heartbeat_interval_seconds": self.daemon.heartbeat_interval_seconds,
                "policy_refresh_seconds": self.daemon.policy_refresh_seconds,
                "watch_debounce_seconds": self.daemon.watch_debounce_seconds,
                "batch_window_seconds": self.daemon.batch_window_seconds,
                "bulk_delete_threshold": self.daemon.bulk_delete_threshold,
                "bulk_delete_window_seconds": self.daemon.bulk_delete_window_seconds,
                "hourly_snapshot_enabled": self.daemon.hourly_snapshot_enabled,
                "daily_snapshot_enabled": self.daemon.daily_snapshot_enabled,
                "idle_verify_enabled": self.daemon.idle_verify_enabled,
                "idle_verify_after_minutes": self.daemon.idle_verify_after_minutes,
            },
            "protection": {
                "auto_protect_desktop": self.protection.auto_protect_desktop,
                "auto_protect_documents": self.protection.auto_protect_documents,
                "auto_protect_downloads": self.protection.auto_protect_downloads,
                "auto_protect_dev_projects": self.protection.auto_protect_dev_projects,
            },
            "backup": {
                "enabled": self.backup.enabled,
                "target": self.backup.target,
                "schedule": self.backup.schedule,
                "time": self.backup.time,
                "gzip": self.backup.gzip,
                "overwrite_latest": self.backup.overwrite_latest,
                "keep_last": self.backup.keep_last,
                "skip_verify": self.backup.skip_verify,
            },
            "retention": {
                "max_vault_size_gb": self.retention.max_vault_size_gb,
                "keep_days": self.retention.keep_days,
                "conservative_prune_only": self.retention.conservative_prune_only,
                "auto_cleanup_enabled": self.retention.auto_cleanup_enabled,
                "last_cleanup_at": self.retention.last_cleanup_at,
                "last_cleanup_status": self.retention.last_cleanup_status,
                "last_cleanup_deleted_versions": (
                    self.retention.last_cleanup_deleted_versions
                ),
                "last_cleanup_reclaimed_bytes": self.retention.last_cleanup_reclaimed_bytes,
                "last_cleanup_error": self.retention.last_cleanup_error,
            },
            "ui": {
                "host": self.ui.host,
                "port": self.ui.port,
                "show_advanced_actions": self.ui.show_advanced_actions,
            },
        }


def get_config_path() -> Path:
    return get_safevault_home() / "config.toml"


def load_config(path: Path | None = None) -> SafeVaultConfig:
    config_path = path or get_config_path()
    if not config_path.exists():
        return SafeVaultConfig()
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SafeVaultError(f"invalid config.toml: {exc}") from exc
    if not isinstance(data, dict):
        raise SafeVaultError("invalid config.toml: expected TOML table")
    return SafeVaultConfig.from_dict(data)


def save_config(config: SafeVaultConfig, path: Path | None = None) -> None:
    ensure_home_layout()
    config = normalize_config_paths(config)
    validate_backup_target(config.backup.target)
    config_path = path or get_config_path()
    atomic_write_bytes(config_path, _to_toml(config).encode("utf-8"))


def normalize_config_paths(config: SafeVaultConfig) -> SafeVaultConfig:
    target = _normalize_optional_path(config.backup.target)
    if target == config.backup.target:
        return config
    return replace(config, backup=replace(config.backup, target=target))


def validate_backup_target(
    target: str | None,
    *,
    protected_roots: list[Path] | None = None,
    allow_inside_protected: bool = False,
) -> None:
    if not target:
        return
    backup_path = Path(target).expanduser().resolve(strict=False)
    home = get_safevault_home().resolve(strict=False)
    if backup_path == home or backup_path.is_relative_to(home):
        raise SafeVaultError("backup target must not be inside SAFEVAULT_HOME")
    if protected_roots and not allow_inside_protected:
        for root in protected_roots:
            root_path = root.expanduser().resolve(strict=False)
            if backup_path == root_path or backup_path.is_relative_to(root_path):
                raise SafeVaultError("backup target must not be inside a protected root")


def with_backup(
    config: SafeVaultConfig,
    *,
    target: Path | None = None,
    schedule: BackupSchedule | None = None,
    time: str | None = None,
    enabled: bool | None = None,
) -> SafeVaultConfig:
    backup = config.backup
    if target is not None:
        backup = replace(backup, target=_normalize_optional_path(str(target)))
    if schedule is not None:
        backup = replace(backup, schedule=_backup_schedule(schedule))
    if time is not None:
        backup = replace(backup, time=_backup_time(time))
    if enabled is not None:
        backup = replace(backup, enabled=enabled)
    return replace(config, backup=backup)


def _normalize_optional_path(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return str(Path(text).expanduser().resolve(strict=False))


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _backup_schedule(value: object) -> BackupSchedule:
    schedule = str(value)
    if schedule not in {"manual", "daily", "weekly"}:
        raise SafeVaultError("backup.schedule must be one of: manual, daily, weekly")
    return cast(BackupSchedule, schedule)


def _backup_time(value: object) -> str:
    text = str(value)
    parts = text.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise SafeVaultError("backup.time must use HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour > 23 or minute > 59:
        raise SafeVaultError("backup.time must use HH:MM")
    return f"{hour:02d}:{minute:02d}"


def _positive_int(value: object, name: str) -> int:
    number = int(str(value))
    if number <= 0:
        raise SafeVaultError(f"{name} must be positive")
    return number


def _nonnegative_int(value: object, name: str) -> int:
    number = int(str(value))
    if number < 0:
        raise SafeVaultError(f"{name} must not be negative")
    return number


def _port_int(value: object) -> int:
    number = _positive_int(value, "ui.port")
    if number > 65535:
        raise SafeVaultError("ui.port must be between 1 and 65535")
    return number


def _to_toml(config: SafeVaultConfig) -> str:
    data = config.to_dict()
    lines: list[str] = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        assert isinstance(values, dict)
        for key, value in values.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    return "\n".join(lines)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return '""'
    return json.dumps(str(value))
