"""Tests for the behaviour log (jarvis/session/behavior_log.py).

The log is an append-only JSONL file bounded to the most recent N records. The
trimming and the recent()/count() readers are the behaviour worth pinning: the
profile refiner learns only from the last N notes, so the cap must actually hold.
A real temp file exercises the round-trip.
"""

import tempfile
import unittest
from pathlib import Path

from jarvis.session.behavior_log import BehaviorLog


class BehaviorLogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "behavior.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def _log(self, max_records=100):
        return BehaviorLog(path=self.path, max_records=max_records)

    def _record(self, log, text="hi"):
        log.record(user_input=text, response_chars=42,
                   solution_strategy="direct", context_strategy="none", had_task=False)

    def test_absent_log_counts_zero_and_recent_is_empty(self):
        log = self._log()
        self.assertEqual(log.count(), 0)
        self.assertEqual(log.recent(5), [])

    def test_record_appends_and_count_grows(self):
        log = self._log()
        self._record(log)
        self._record(log)
        self.assertEqual(log.count(), 2)

    def test_a_record_captures_the_expected_fields(self):
        log = self._log()
        log.record(user_input="hello", response_chars=100,
                   solution_strategy="step_by_step", context_strategy="topics", had_task=True)
        (entry,) = log.recent(1)
        self.assertEqual(entry["user_input"], "hello")
        self.assertEqual(entry["user_chars"], 5)
        self.assertEqual(entry["response_chars"], 100)
        self.assertEqual(entry["solution_strategy"], "step_by_step")
        self.assertTrue(entry["had_task"])
        self.assertIn("ts", entry)

    def test_recent_returns_oldest_first_and_at_most_n(self):
        log = self._log()
        for i in range(5):
            self._record(log, text=f"msg-{i}")
        recent = log.recent(3)
        self.assertEqual([r["user_input"] for r in recent], ["msg-2", "msg-3", "msg-4"])

    def test_the_log_is_trimmed_to_max_records_on_write(self):
        log = self._log(max_records=3)
        for i in range(6):
            self._record(log, text=f"msg-{i}")
        self.assertEqual(log.count(), 3)
        self.assertEqual([r["user_input"] for r in log.recent(10)],
                        ["msg-3", "msg-4", "msg-5"])

    def test_a_malformed_line_is_skipped_not_fatal(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"user_input": "ok"}\nnot json\n', encoding="utf-8")
        log = self._log()
        recent = log.recent(10)
        self.assertEqual([r["user_input"] for r in recent], ["ok"])


if __name__ == "__main__":
    unittest.main()
