"""Tests for the invariant store (jarvis/session/invariant_store.py).

The single global invariants.md is user-authored, so the store's job is narrow:
scaffold it once from a template, read it back, and treat a blank file as "no
active invariants". init() must be idempotent — running it on an existing file
must not clobber the user's hand-written rules.
"""

import tempfile
import unittest
from pathlib import Path

from jarvis.session.invariant_store import InvariantStore


class InvariantStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = InvariantStore(directory=Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_absent_file_reads_as_none(self):
        self.assertFalse(self.store.exists())
        self.assertIsNone(self.store.read())
        self.assertIsNone(self.store.read_active())

    def test_init_scaffolds_the_template_and_reports_created(self):
        self.assertTrue(self.store.init())
        self.assertTrue(self.store.exists())
        self.assertIn("# Invariants", self.store.read())

    def test_init_is_idempotent_and_never_overwrites(self):
        self.store.write("# Invariants\n\n- Kotlin only\n")
        created = self.store.init()
        self.assertFalse(created)                       # already existed
        self.assertIn("- Kotlin only", self.store.read())  # user content intact

    def test_read_active_ignores_a_blank_file(self):
        self.store.write("   \n\n")
        self.assertTrue(self.store.exists())
        self.assertIsNone(self.store.read_active())

    def test_read_active_returns_real_content(self):
        self.store.write("# Invariants\n\n- budget = $0\n")
        self.assertIn("budget = $0", self.store.read_active())

    def test_path_for_points_at_invariants_md(self):
        self.assertEqual(self.store.path_for().name, "invariants.md")


if __name__ == "__main__":
    unittest.main()
