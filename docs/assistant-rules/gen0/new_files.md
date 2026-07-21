# gen0 — files created by this generation

## `jarvis/session/note_store.py`

```python
"""
Standalone note persistence.

A note is a single piece of free text the user wants to keep across sessions.
Notes are independent of both chat threads and tasks: they carry no stage, no
transcript and no context — they are not injected into prompts.

All notes live in one JSON file, ~/.jarvis/notes.json:
  [
    {
      "id":         "a1b2c3d4",
      "text":       "Check the reranker latency before the demo",
      "created_at": "2026-07-21T09:00:00"
    },
    …
  ]

A single file (rather than file-per-note, as tasks use) because notes are small
and are always read as a whole list.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class NoteStore:
    def __init__(self, path: Path | None = None) -> None:
        # Resolve home at instantiation (not import) so $HOME-based test isolation works.
        self._path = path or (Path.home() / ".jarvis" / "notes.json")

    def add(self, text: str) -> dict:
        """Append a note. Returns the created note dict."""
        note = {
            "id": uuid4().hex[:8],
            "text": text,
            "created_at": _now(),
        }
        notes = self.list_all()
        notes.append(note)
        self._write(notes)
        return note

    def list_all(self) -> list[dict]:
        """Return all notes, oldest first. Malformed entries are skipped."""
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        return [n for n in data if isinstance(n, dict) and "id" in n and "text" in n]

    def find(self, query: str) -> dict | None:
        """Find a note by exact id, then by unique id prefix. None if not found/ambiguous."""
        notes = self.list_all()
        for note in notes:
            if note["id"] == query:
                return note
        candidates = [n for n in notes if n["id"].startswith(query)]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def delete(self, note_id: str) -> dict | None:
        """Delete the note matching note_id (exact id or unique prefix). Returns it, or None."""
        note = self.find(note_id)
        if note is None:
            return None
        self._write([n for n in self.list_all() if n["id"] != note["id"]])
        return note

    # ── Internal ───────────────────────────────────────────────────────────────

    def _write(self, notes: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
```

## `tests/test_note_store.py`

```python
"""Tests for standalone note persistence and the `notes` REPL command."""

import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from jarvis.repl.commands import handle_notes
from jarvis.session.note_store import NoteStore


class NoteStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = NoteStore(Path(self._tmp.name) / "notes.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_returns_note_with_id(self):
        note = self.store.add("buy milk")
        self.assertEqual(note["text"], "buy milk")
        self.assertTrue(note["id"])
        self.assertTrue(note["created_at"])

    def test_list_empty_when_no_file(self):
        self.assertEqual(self.store.list_all(), [])

    def test_notes_persist_across_store_instances(self):
        self.store.add("first")
        self.store.add("second")
        reopened = NoteStore(Path(self._tmp.name) / "notes.json")
        self.assertEqual([n["text"] for n in reopened.list_all()], ["first", "second"])

    def test_ids_are_unique(self):
        ids = {self.store.add(f"note {i}")["id"] for i in range(10)}
        self.assertEqual(len(ids), 10)

    def test_delete_removes_only_the_target(self):
        keep = self.store.add("keep")
        drop = self.store.add("drop")
        deleted = self.store.delete(drop["id"])
        self.assertEqual(deleted["id"], drop["id"])
        self.assertEqual([n["id"] for n in self.store.list_all()], [keep["id"]])

    def test_delete_unknown_id_returns_none(self):
        self.assertIsNone(self.store.delete("nope"))

    def test_delete_by_unique_id_prefix(self):
        note = self.store.add("prefixed")
        self.assertIsNotNone(self.store.delete(note["id"][:4]))
        self.assertEqual(self.store.list_all(), [])

    def test_find_ambiguous_prefix_returns_none(self):
        # An empty prefix matches every note, so it must be treated as ambiguous.
        self.store.add("a")
        self.store.add("b")
        self.assertIsNone(self.store.find(""))

    def test_corrupt_file_reads_as_empty(self):
        path = Path(self._tmp.name) / "notes.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.list_all(), [])

    def test_malformed_entries_are_skipped(self):
        path = Path(self._tmp.name) / "notes.json"
        path.write_text(json.dumps([{"id": "a1", "text": "ok"}, {"bad": 1}, "x"]), encoding="utf-8")
        self.assertEqual([n["text"] for n in self.store.list_all()], ["ok"])


class NotesCommandTest(unittest.TestCase):
    """The handler resolves NoteStore() against $HOME, so isolate HOME."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._home = unittest.mock.patch.dict(
            "os.environ", {"HOME": self._tmp.name}
        )
        self._home.start()

    def tearDown(self):
        self._home.stop()
        self._tmp.cleanup()

    def test_no_args_shows_usage(self):
        self.assertIn("Usage: notes add", handle_notes([]))

    def test_unknown_subcommand(self):
        self.assertIn("Unknown notes sub-command", handle_notes(["frobnicate"]))

    def test_add_list_delete_round_trip(self):
        self.assertIn("Note added", handle_notes(["add", "ship", "the", "release"]))
        listed = handle_notes(["list"])
        self.assertIn("ship the release", listed)

        note_id = NoteStore().list_all()[0]["id"]
        self.assertIn("deleted", handle_notes(["delete", note_id]))
        self.assertIn("No saved notes", handle_notes(["list"]))

    def test_add_requires_text(self):
        self.assertEqual(handle_notes(["add"]), "Usage: notes add <text>")

    def test_delete_requires_id(self):
        self.assertEqual(handle_notes(["delete"]), "Usage: notes delete <id>")

    def test_delete_unknown_id_reports_not_found(self):
        self.assertIn("Note not found", handle_notes(["delete", "deadbeef"]))


if __name__ == "__main__":
    unittest.main()
```
