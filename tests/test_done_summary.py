"""Tests for splitting the done-stage reply into (summary, deliverable)."""

import unittest

from jarvis.repl.loop import _split_summary


class SplitSummaryTest(unittest.TestCase):
    def test_summary_line_is_extracted(self):
        text = "SUMMARY: A 2-serving pasta recipe.\n\n# Recipe\nstep one\nstep two"
        summary, deliverable = _split_summary(text)
        self.assertEqual(summary, "A 2-serving pasta recipe.")
        self.assertEqual(deliverable, "# Recipe\nstep one\nstep two")

    def test_case_insensitive_prefix(self):
        summary, deliverable = _split_summary("summary: done thing\n\nbody")
        self.assertEqual(summary, "done thing")
        self.assertEqual(deliverable, "body")

    def test_fallback_without_summary_line(self):
        text = "# The Deliverable\nline two"
        summary, deliverable = _split_summary(text)
        self.assertEqual(summary, "# The Deliverable")
        self.assertEqual(deliverable, text)


if __name__ == "__main__":
    unittest.main()
