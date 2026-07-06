from __future__ import annotations

from dataclasses import dataclass

from safevault.watcher import SafeVaultEventHandler


@dataclass
class Event:
    event_type: str
    src_path: str
    is_directory: bool = False


def test_handler_classifies_events(project) -> None:
    handler = SafeVaultEventHandler(project, snapshot_func=lambda path, reason: 1)
    assert handler.classify_event(Event("modified", str(project / "a.txt"))) == "modified"


def test_debounce_coalesces_repeated_events(project) -> None:
    calls = []
    handler = SafeVaultEventHandler(
        project, snapshot_func=lambda path, reason: calls.append((path, reason)) or 1
    )
    path = project / "a.txt"
    path.write_text("x", encoding="utf-8")
    handler.note_event("modified", path, now=1.0)
    handler.note_event("modified", path, now=1.5)
    assert not handler.flush(now=2.0)
    assert handler.flush(now=2.6)
    assert len(calls) == 1


def test_delete_event_can_trigger_snapshot(project) -> None:
    calls = []
    handler = SafeVaultEventHandler(
        project, snapshot_func=lambda path, reason: calls.append(reason) or 1
    )
    path = project / "gone.txt"
    handler.note_event("deleted", path, now=1.0)
    assert handler.flush(now=2.1)
    assert calls == ["watch"]


def test_batch_deletion_warning_triggers_over_threshold(project) -> None:
    warnings = []
    handler = SafeVaultEventHandler(
        project, snapshot_func=lambda path, reason: 1, warn_func=warnings.append
    )
    for index in range(21):
        handler.note_event("deleted", project / f"{index}.txt", now=float(index))
    assert warnings
