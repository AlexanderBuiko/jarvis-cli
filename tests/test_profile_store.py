"""Tests for the profile store and its markdown section helpers
(jarvis/session/profile_store.py).

ProfileStore is pure file I/O plus small markdown helpers, so a real temp
directory exercises it faithfully — no mocking. The section helpers matter most:
`personalize` rewrites only the '## Style' body and must leave Constraints and
Context untouched.
"""

import tempfile
import unittest
from pathlib import Path

from jarvis.session.profile_store import (
    ProfileStore,
    extract_section,
    replace_section,
)


class ProfileStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ProfileStore(directory=Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_absent_profile_reads_as_none(self):
        self.assertFalse(self.store.exists())
        self.assertIsNone(self.store.read())
        self.assertIsNone(self.store.read_active())

    def test_write_default_creates_the_three_sections(self):
        self.store.write_default()
        self.assertTrue(self.store.exists())
        content = self.store.read()
        for header in ("## Style", "## Constraints", "## Context"):
            self.assertIn(header, content)

    def test_write_sections_bullets_each_answer(self):
        self.store.write_sections("terse replies", "no external APIs", "backend engineer")
        self.assertEqual(self.store.read_style(), "- terse replies")
        content = self.store.read()
        self.assertIn("- no external APIs", content)
        self.assertIn("- backend engineer", content)

    def test_empty_answer_becomes_the_none_recorded_bullet(self):
        self.store.write_sections("", "", "")
        self.assertEqual(self.store.read_style(), "- (none recorded)")

    def test_read_active_ignores_a_whitespace_only_file(self):
        self.store.write("   \n\n  ")
        self.assertIsNone(self.store.read_active())

    def test_replace_style_changes_only_the_style_section(self):
        self.store.write_sections("old style", "keep me", "and me")
        ok = self.store.replace_style("- new style A\n- new style B")
        self.assertTrue(ok)
        self.assertEqual(self.store.read_style(), "- new style A\n- new style B")
        content = self.store.read()
        self.assertIn("- keep me", content)      # Constraints preserved
        self.assertIn("- and me", content)       # Context preserved
        self.assertNotIn("old style", content)

    def test_replace_style_returns_false_when_no_profile_exists(self):
        self.assertFalse(self.store.replace_style("- anything"))


class SectionHelperTest(unittest.TestCase):
    _DOC = "# Profile\n\n## Style\n- a\n- b\n\n## Constraints\n- c\n"

    def test_extract_section_returns_body_without_the_header(self):
        self.assertEqual(extract_section(self._DOC, "## Style"), "- a\n- b")

    def test_extract_missing_section_is_none(self):
        self.assertIsNone(extract_section(self._DOC, "## Nope"))

    def test_extract_is_case_insensitive_on_the_header(self):
        self.assertEqual(extract_section(self._DOC, "## style"), "- a\n- b")

    def test_replace_section_preserves_following_sections(self):
        out = replace_section(self._DOC, "## Style", "- z")
        self.assertIn("- z", out)
        self.assertIn("## Constraints", out)
        self.assertIn("- c", out)
        self.assertNotIn("- a", out)

    def test_replace_missing_section_is_none(self):
        self.assertIsNone(replace_section(self._DOC, "## Nope", "- z"))


if __name__ == "__main__":
    unittest.main()
