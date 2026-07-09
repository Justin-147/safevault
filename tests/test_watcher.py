from __future__ import annotations

from dataclasses import dataclass

from safevault.watcher import SafeVaultEventHandler


@dataclass
class Event:
    event_type: str
    src_path: str
    dest_path: str = ""
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
    assert warnings == ["High-risk warning: more than 20 delete events in 30 seconds"]


def test_bulk_delete_warning_is_rate_limited(project) -> None:
    warnings = []
    handler = SafeVaultEventHandler(
        project,
        snapshot_func=lambda path, reason: 1,
        warn_func=warnings.append,
        bulk_delete_threshold=1,
        bulk_delete_window_seconds=30,
        bulk_delete_warning_cooldown_seconds=60,
    )

    handler.note_event("deleted", project / "a.txt", now=1.0)
    handler.note_event("deleted", project / "b.txt", now=2.0)
    handler.note_event("deleted", project / "c.txt", now=3.0)
    handler.note_event("deleted", project / "d.txt", now=63.0)
    handler.note_event("deleted", project / "e.txt", now=64.0)

    assert warnings == [
        "High-risk warning: more than 1 delete events in 30 seconds",
        "High-risk warning: more than 1 delete events in 30 seconds",
    ]


def test_large_change_batch_uses_large_change_snapshot_reason(project) -> None:
    warnings = []
    calls = []
    handler = SafeVaultEventHandler(
        project,
        snapshot_func=lambda path, reason: calls.append((path, reason)) or 1,
        warn_func=warnings.append,
        bulk_change_threshold=2,
    )

    handler.note_event("modified", project / "a.txt", now=1.0)
    handler.note_event("created", project / "b.txt", now=2.0)
    handler.note_event("modified", project / "c.txt", now=3.0)
    assert handler.flush(now=4.5)

    assert warnings == ["High-risk warning: more than 2 file change events in 30 seconds"]
    assert calls == [(project, "after-large-change")]


def test_suspicious_encrypted_extension_batch_uses_emergency_checkpoint(
    project,
) -> None:
    warnings = []
    calls = []
    handler = SafeVaultEventHandler(
        project,
        snapshot_func=lambda path, reason: calls.append((path, reason)) or 1,
        warn_func=warnings.append,
        suspicious_extension_threshold=2,
    )

    handler.note_event("created", project / "a.locked", now=1.0)
    handler.note_event("modified", project / "b.encrypted", now=2.0)
    handler.note_event("created", project / "c.crypt", now=3.0)
    assert handler.flush(now=4.5)

    assert warnings == [
        "Emergency warning: suspicious encrypted-file extension activity exceeded "
        "2 events in 30 seconds"
    ]
    assert calls == [(project, "emergency-mass-change")]


def test_move_file_out_of_root_records_deleted_marker(project, tmp_path) -> None:
    deleted = []
    handler = SafeVaultEventHandler(
        project,
        snapshot_func=lambda path, reason: 1,
        deleted_func=lambda root, path: deleted.append((root, path)),
    )
    src = project / "moved.txt"
    dest = tmp_path / "outside.txt"

    handler.on_any_event(Event("moved", str(src), str(dest)))

    assert deleted == [(project, src)]


def test_move_file_within_root_records_moved_callback(project) -> None:
    moved = []
    handler = SafeVaultEventHandler(
        project,
        snapshot_func=lambda path, reason: 1,
        moved_func=lambda root, src, dest: moved.append((root, src, dest)),
    )
    src = project / "old.txt"
    dest = project / "folder" / "new.txt"

    handler.on_any_event(Event("moved", str(src), str(dest)))

    assert moved == [(project, src, dest)]
