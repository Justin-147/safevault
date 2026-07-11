from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from safevault.db import connect, list_roots
from safevault.ignore import is_ignored
from safevault.mass_change import has_suspicious_encryption_extension
from safevault.snapshot import create_snapshot

SnapshotFunc = Callable[[Path, str], int]


class SafeVaultEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        root: Path,
        snapshot_func: SnapshotFunc | None = None,
        debounce_seconds: float = 1.0,
        warn_func: Callable[[str], None] | None = None,
        deleted_func: Callable[[Path, Path], None] | None = None,
        moved_func: Callable[[Path, Path, Path], None] | None = None,
        bulk_delete_threshold: int = 20,
        bulk_change_threshold: int = 100,
        suspicious_extension_threshold: int = 25,
        bulk_delete_window_seconds: float = 30,
        bulk_delete_warning_cooldown_seconds: float = 60,
        auto_flush: bool = True,
    ) -> None:
        self.root = root
        self.snapshot_func = snapshot_func or (lambda path, reason: create_snapshot(path, reason))
        self.debounce_seconds = debounce_seconds
        self.warn_func = warn_func or print
        self.deleted_func = deleted_func
        self.moved_func = moved_func
        self.bulk_delete_threshold = bulk_delete_threshold
        self.bulk_change_threshold = bulk_change_threshold
        self.suspicious_extension_threshold = suspicious_extension_threshold
        self.bulk_delete_window_seconds = bulk_delete_window_seconds
        self.bulk_delete_warning_cooldown_seconds = bulk_delete_warning_cooldown_seconds
        self.auto_flush = auto_flush
        self.last_bulk_delete_warning_at = -bulk_delete_warning_cooldown_seconds
        self.last_bulk_change_warning_at = -bulk_delete_warning_cooldown_seconds
        self.last_suspicious_extension_warning_at = -bulk_delete_warning_cooldown_seconds
        self.pending = False
        self.large_change_pending = False
        self.emergency_change_pending = False
        self.last_event_at = 0.0
        self.delete_times: list[float] = []
        self.change_times: list[float] = []
        self.suspicious_extension_times: list[float] = []
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def classify_event(self, event: FileSystemEvent) -> str:
        return event.event_type

    def note_event(self, event_type: str, path: str | Path, now: float | None = None) -> None:
        path_obj = Path(path)
        if is_ignored(self.root, path_obj):
            return
        current_time = time.monotonic() if now is None else now
        with self._lock:
            self.pending = True
            self.last_event_at = current_time
            if event_type in {"created", "modified", "deleted", "moved"}:
                self.change_times.append(current_time)
                self.change_times = [
                    value
                    for value in self.change_times
                    if current_time - value <= self.bulk_delete_window_seconds
                ]
                if (
                    len(self.change_times) > self.bulk_change_threshold
                    and current_time - self.last_bulk_change_warning_at
                    >= self.bulk_delete_warning_cooldown_seconds
                ):
                    self.large_change_pending = True
                    self.last_bulk_change_warning_at = current_time
                    self.warn_func(
                        "High-risk warning: more than "
                        f"{self.bulk_change_threshold} file change events in "
                        f"{int(self.bulk_delete_window_seconds)} seconds"
                    )
                if has_suspicious_encryption_extension(path_obj):
                    self.suspicious_extension_times.append(current_time)
                    self.suspicious_extension_times = [
                        value
                        for value in self.suspicious_extension_times
                        if current_time - value <= self.bulk_delete_window_seconds
                    ]
                    if (
                        len(self.suspicious_extension_times)
                        > self.suspicious_extension_threshold
                        and current_time - self.last_suspicious_extension_warning_at
                        >= self.bulk_delete_warning_cooldown_seconds
                    ):
                        self.emergency_change_pending = True
                        self.last_suspicious_extension_warning_at = current_time
                        self.warn_func(
                            "Emergency warning: suspicious encrypted-file extension "
                            f"activity exceeded {self.suspicious_extension_threshold} "
                            f"events in {int(self.bulk_delete_window_seconds)} seconds"
                        )
            if event_type == "deleted":
                if self.deleted_func is not None:
                    self.deleted_func(self.root, path_obj)
                self.delete_times.append(current_time)
                self.delete_times = [
                    value
                    for value in self.delete_times
                    if current_time - value <= self.bulk_delete_window_seconds
                ]
                if (
                    len(self.delete_times) > self.bulk_delete_threshold
                    and current_time - self.last_bulk_delete_warning_at
                    >= self.bulk_delete_warning_cooldown_seconds
                ):
                    self.last_bulk_delete_warning_at = current_time
                    self.warn_func(
                        "High-risk warning: more than "
                        f"{self.bulk_delete_threshold} delete events in "
                        f"{int(self.bulk_delete_window_seconds)} seconds"
                    )
            if now is None and self.auto_flush:
                self._schedule_timer()

    def enable_auto_flush(self) -> None:
        with self._lock:
            self.auto_flush = True
            pending = self.pending
        if pending:
            self._schedule_timer()

    def _schedule_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self.debounce_seconds, self.flush)
        self._timer.daemon = True
        self._timer.start()

    def should_flush(self, now: float | None = None) -> bool:
        current_time = time.monotonic() if now is None else now
        return self.pending and current_time - self.last_event_at >= self.debounce_seconds

    def flush(self, now: float | None = None) -> bool:
        if now is not None and not self.should_flush(now):
            return False
        with self._lock:
            if not self.pending:
                return False
            self.pending = False
            if self.emergency_change_pending:
                reason = "emergency-mass-change"
            elif self.large_change_pending:
                reason = "after-large-change"
            else:
                reason = "watch"
            self.large_change_pending = False
            self.emergency_change_pending = False
        self.snapshot_func(self.root, reason)
        return True

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type == "moved":
            src_path = Path(str(event.src_path))
            dest_text = getattr(event, "dest_path", "")
            dest_path = Path(str(dest_text)) if dest_text else None
            if self._is_under_root(src_path) and (
                dest_path is None or not self._is_under_root(dest_path)
            ):
                self.note_event("deleted", src_path)
                return
            if dest_path is not None and self._is_under_root(dest_path):
                if self.moved_func is not None:
                    self.moved_func(self.root, src_path, dest_path)
                self.note_event("moved", dest_path)
                return
        event_path = getattr(event, "dest_path", None) or event.src_path
        self.note_event(self.classify_event(event), str(event_path))

    def _is_under_root(self, path: Path) -> bool:
        try:
            resolved = path.expanduser().resolve(strict=False)
            root = self.root.expanduser().resolve(strict=False)
        except OSError:
            return False
        return resolved == root or resolved.is_relative_to(root)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()


def watch_roots() -> None:
    conn = connect()
    roots = list_roots(conn)
    conn.close()
    observer = Observer()
    handlers: list[SafeVaultEventHandler] = []
    for root in roots:
        root_path = Path(root.path)
        handler = SafeVaultEventHandler(root_path)
        handlers.append(handler)
        observer.schedule(handler, str(root_path), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for handler in handlers:
            handler.stop()
        observer.stop()
        observer.join()
