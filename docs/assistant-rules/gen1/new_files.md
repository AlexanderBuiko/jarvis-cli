# gen1 — files created by this generation

## `jarvis/session/notes_store.py`

```python
"""
notes_store — durable, free-form user notes.

Notes are the user's own scratch memory: short pieces of text they want to
survive a restart. Unlike invariants or profile.md they are never injected into
a prompt and never read by the agent, so they live entirely outside the memory
pipeline and are addressed only by the ``notes`` command.

Storage is ONE JSON file holding a list, not a file per note as TaskStore does.
A task carries a transcript and is written on every stage transition, so
per-file writes keep them independent; notes are a handful of short strings
read and rewritten as a whole, where a single file is cheaper and keeps
ordering explicit rather than derived from a directory listing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_FILENAME = "notes.json"

# Short enough to retype from a listing, wide enough that collisions are
# implausible at the scale of a personal note list.
_ID_LENGTH = 8


@dataclass
class Note:
    """One stored note."""

    id: str
    text: str
    created_at: str     # UTC ISO-8601, second resolution


class NotesStore:
    """Notes persisted as a JSON list under ~/.jarvis/notes.json."""

    def __init__(self, directory: Path | None = None) -> None:
        # Resolve home at instantiation (not import) so $HOME-based test isolation works.
        self._path = (directory or (Path.home() / ".jarvis")) / _FILENAME

    def add(self, text: str) -> Note:
        """Append a note and return it, with a freshly generated short id."""
        note = Note(id=uuid4().hex[:_ID_LENGTH], text=text, created_at=_now())
        notes = self.list_all()
        notes.append(note)
        self._write(notes)
        return note

    def list_all(self) -> list[Note]:
        """Return every note in insertion order. Unreadable storage yields []."""
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        notes = []
        for entry in data:
            if not isinstance(entry, dict) or "text" not in entry:
                continue
            notes.append(Note(
                id=str(entry.get("id") or uuid4().hex[:_ID_LENGTH]),
                text=str(entry["text"]),
                created_at=str(entry.get("created_at", "")),
            ))
        return notes

    def delete(self, note_id: str) -> Note | None:
        """Delete by exact id or unambiguous id prefix. Returns the note, or None.

        An ambiguous prefix deletes nothing — removing the wrong note is not
        recoverable, so the caller is made to disambiguate instead.
        """
        notes = self.list_all()
        matches = [n for n in notes if n.id == note_id] or \
                  [n for n in notes if n.id.startswith(note_id)]
        if len(matches) != 1:
            return None
        target = matches[0]
        self._write([n for n in notes if n.id != target.id])
        return target

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write(self, notes: list[Note]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"id": n.id, "text": n.text, "created_at": n.created_at} for n in notes]
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
```

## `tests/test_notes_store.py`

```python
"""Tests for the notes store and the `notes` command handlers."""

import tempfile
import unittest
from pathlib import Path

from jarvis.session.notes_store import NotesStore
from jarvis.repl.commands import handle_notes_add, handle_notes_list, handle_notes_delete


class NotesStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = NotesStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_added_note_is_returned_by_list(self):
        note = self.store.add("buy milk")
        self.assertEqual([n.text for n in self.store.list_all()], ["buy milk"])
        self.assertEqual(len(note.id), 8)

    def test_notes_survive_a_new_store_instance(self):
        self.store.add("persisted")
        reopened = NotesStore(Path(self._tmp.name))
        self.assertEqual([n.text for n in reopened.list_all()], ["persisted"])

    def test_list_preserves_insertion_order(self):
        for text in ("first", "second", "third"):
            self.store.add(text)
        self.assertEqual(
            [n.text for n in self.store.list_all()], ["first", "second", "third"]
        )

    def test_delete_removes_only_the_named_note(self):
        keep = self.store.add("keep")
        drop = self.store.add("drop")
        self.assertEqual(self.store.delete(drop.id).text, "drop")
        self.assertEqual([n.id for n in self.store.list_all()], [keep.id])

    def test_delete_accepts_an_unambiguous_id_prefix(self):
        note = self.store.add("prefixed")
        self.assertIsNotNone(self.store.delete(note.id[:4]))
        self.assertEqual(self.store.list_all(), [])

    def test_delete_of_unknown_id_returns_none_and_changes_nothing(self):
        self.store.add("safe")
        self.assertIsNone(self.store.delete("nosuchid"))
        self.assertEqual(len(self.store.list_all()), 1)

    def test_ambiguous_prefix_deletes_nothing(self):
        notes = [self.store.add(f"note {i}") for i in range(20)]
        shared = notes[0].id[:1]
        if sum(n.id.startswith(shared) for n in notes) < 2:
            self.skipTest("random ids did not collide on the first character")
        self.assertIsNone(self.store.delete(shared))
        self.assertEqual(len(self.store.list_all()), 20)

    def test_listing_missing_file_is_empty_not_an_error(self):
        self.assertEqual(NotesStore(Path(self._tmp.name) / "absent").list_all(), [])

    def test_corrupt_storage_degrades_to_empty(self):
        (Path(self._tmp.name) / "notes.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.list_all(), [])


class NotesCommandTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = NotesStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_joins_the_whole_argument_list(self):
        handle_notes_add(["review", "the", "PR"], self.store)
        self.assertEqual([n.text for n in self.store.list_all()], ["review the PR"])

    def test_add_without_text_returns_usage(self):
        self.assertIn("Usage", handle_notes_add([], self.store))
        self.assertEqual(self.store.list_all(), [])

    def test_list_when_empty_explains_how_to_add(self):
        self.assertIn("No notes yet", handle_notes_list(self.store))

    def test_list_renders_id_and_text(self):
        note = self.store.add("ship it")
        output = handle_notes_list(self.store)
        self.assertIn(note.id, output)
        self.assertIn("ship it", output)

    def test_delete_without_id_returns_usage(self):
        self.assertIn("Usage", handle_notes_delete([], self.store))

    def test_delete_of_unknown_id_is_reported_not_silent(self):
        self.assertIn("No single note", handle_notes_delete(["zzzz"], self.store))
```
