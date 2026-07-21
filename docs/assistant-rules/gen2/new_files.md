# gen2 — files created by this generation

## `jarvis/session/note_store.py`

```python
"""
Notes — short free-text reminders the user writes by hand.

A note is a single line of text with an id and a timestamp. Unlike tasks, a note
has no state, no stage and no conversation, so the file-per-item layout of
``task_store`` would be wasted here: every operation (list, delete) would have to
scan a directory to rebuild an order that a plain list already has. All notes
therefore live in ONE array under ~/.jarvis/notes.json:

  [
    {"id": "a1b2c3d4", "text": "call the bank", "created_at": "2026-07-22T09:00:00"},
    …
  ]

Order is insertion order — the file is the source of truth for it, so a note keeps
its position no matter when it is read.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_FILENAME = "notes.json"


class NoteStore:
    """All notes in one JSON array. No per-thread or per-task scope."""

    def __init__(self, directory: Path | None = None) -> None:
        # Resolve home at instantiation (not import) so $HOME-based test isolation works.
        self._path = (directory or (Path.home() / ".jarvis")) / _FILENAME

    def add(self, text: str) -> dict:
        """Append a note and return it."""
        note = {"id": uuid4().hex[:8], "text": text, "created_at": _now()}
        notes = self.list_all()
        notes.append(note)
        self._write(notes)
        return note

    def list_all(self) -> list[dict]:
        """Return every note in insertion order, or [] if the file is missing or corrupt."""
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        return [n for n in data if isinstance(n, dict) and "id" in n]

    def find(self, query: str) -> dict | None:
        """Find a note by exact id, then by unique id prefix. Returns None if ambiguous."""
        notes = self.list_all()
        for note in notes:
            if note["id"] == query:
                return note
        candidates = [n for n in notes if n["id"].startswith(query)]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def delete(self, note_id: str) -> bool:
        """Delete the note matching ``note_id`` (exact id or unique prefix)."""
        note = self.find(note_id)
        if note is None:
            return False
        self._write([n for n in self.list_all() if n["id"] != note["id"]])
        return True

    def path_for(self) -> Path:
        """Filesystem path of notes.json."""
        return self._path

    # ── Internal ───────────────────────────────────────────────────────────────

    def _write(self, notes: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
```

## `tests/test_note_store.py`

```python
"""NoteStore persistence and the `notes` command handlers."""

import tempfile
import unittest
from pathlib import Path

from jarvis.repl.commands import handle_notes_add, handle_notes_list, handle_notes_delete
from jarvis.session.note_store import NoteStore


class NoteStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = NoteStore(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_a_note_survives_a_new_store_over_the_same_directory(self):
        self.store.add("call the bank")
        reopened = NoteStore(Path(self._tmp.name))
        self.assertEqual(["call the bank"], [n["text"] for n in reopened.list_all()])

    def test_notes_are_listed_in_insertion_order(self):
        for text in ("first", "second", "third"):
            self.store.add(text)
        self.assertEqual(["first", "second", "third"], [n["text"] for n in self.store.list_all()])

    def test_listing_an_absent_file_returns_no_notes(self):
        self.assertEqual([], self.store.list_all())

    def test_a_corrupt_file_degrades_to_no_notes(self):
        self.store.path_for().parent.mkdir(parents=True, exist_ok=True)
        self.store.path_for().write_text("{not json", encoding="utf-8")
        self.assertEqual([], self.store.list_all())

    def test_delete_accepts_a_unique_id_prefix(self):
        note = self.store.add("call the bank")
        self.assertTrue(self.store.delete(note["id"][:4]))
        self.assertEqual([], self.store.list_all())

    def test_deleting_an_unknown_id_reports_failure_and_keeps_the_notes(self):
        self.store.add("keep me")
        self.assertFalse(self.store.delete("nope"))
        self.assertEqual(1, len(self.store.list_all()))


class NotesHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = NoteStore(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_add_joins_the_whole_argument_list_into_one_note(self):
        handle_notes_add(["buy", "more", "coffee"], self.store)
        self.assertEqual(["buy more coffee"], [n["text"] for n in self.store.list_all()])

    def test_add_without_text_returns_usage_and_saves_nothing(self):
        self.assertIn("Usage:", handle_notes_add([], self.store))
        self.assertEqual([], self.store.list_all())

    def test_list_shows_each_note_id_and_text(self):
        note = self.store.add("call the bank")
        output = handle_notes_list(self.store)
        self.assertIn(note["id"], output)
        self.assertIn("call the bank", output)

    def test_list_on_an_empty_store_explains_how_to_add(self):
        self.assertIn("notes add", handle_notes_list(self.store))

    def test_delete_removes_the_note(self):
        note = self.store.add("call the bank")
        self.assertIn("Deleted", handle_notes_delete([note["id"]], self.store))
        self.assertEqual([], self.store.list_all())

    def test_delete_of_an_unknown_id_reports_it(self):
        output = handle_notes_delete(["deadbeef"], self.store)
        self.assertIn("No note matches", output)


if __name__ == "__main__":
    unittest.main()
```
