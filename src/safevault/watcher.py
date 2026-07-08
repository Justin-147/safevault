from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from safevault.db import connect, list_roots
from safevault.ignore import is_ignored
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
        bulk_delete_threshold: int = 20,
        bulk_delete_window_seconds: float = 30,
    ) -> None:
        self.root = root
        self.snapshot_func = snapshot_func or (lambda path, reason: create_snapshot(path, reason))
        self.debounce_seconds = debounce_seconds
        self.warn_func = warn_func or print
        self.deleted_func = deleted_func
        self.bulk_delete_threshold = bulk_delete_threshold
        self.bulk_delete_window_seconds = bulk_delete_window_seconds
        self.pending = False
        self.last_event_at = 0.0
        self.delete_times: list[float] = []
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
            if event_type == "deleted":
                if self.deleted_func is not None:
                    self.deleted_func(self.root, path_obj)
                self.delete_times.append(current_time)
                self.delete_times = [
                    value
                    for value in self.delete_times
                    if current_time - value <= self.bulk_delete_window_seconds
                ]
                if len(self.delete_times) > self.bulk_delete_threshold:
                    self.warn_func(
                        "High-risk warning: more than "
                        f"{self.bulk_delete_threshold} delete events in "
                        f"{int(self.bulk_delete_window_seconds)} seconds"
                    )
            if now is None:
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
        self.snapshot_func(self.root, "watch")
        return True

    def on_any_event(self, event: FileSystemEvent) -> None:
        src_path = getattr(event, "dest_path", None) or event.src_path
        self.note_event(self.classify_event(event), str(src_path))

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
