"""Tests for offline MCQ generation (jarvis.quiz.builder)."""

import json
import unittest

from jarvis.quiz.builder import (
    MCQ,
    _has_verbatim_span,
    _norm_words,
    _parse_mcq,
    _topic_for,
    _valid_shape,
    build_pool,
    mcqs_to_json,
    validate_pool,
)


def _mcq_json(question="What is X?", options=None, correct=1):
    options = options or ["a", "b", "c", "d"]
    return json.dumps({"question": question, "options": options, "correct_index": correct})


class ParseTest(unittest.TestCase):
    def test_parses_bare_and_fenced_json(self):
        self.assertEqual(_parse_mcq(_mcq_json())["question"], "What is X?")
        fenced = "Sure!\n```json\n" + _mcq_json() + "\n```"
        self.assertEqual(_parse_mcq(fenced)["correct_index"], 1)

    def test_returns_none_without_json(self):
        self.assertIsNone(_parse_mcq("no json here"))


class ShapeTest(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(_valid_shape({"question": "q", "options": ["a", "b", "c", "d"], "correct_index": 0}))

    def test_rejects_wrong_option_count_and_dupes_and_range(self):
        self.assertFalse(_valid_shape({"question": "q", "options": ["a", "b", "c"], "correct_index": 0}))
        self.assertFalse(_valid_shape({"question": "q", "options": ["a", "a", "b", "c"], "correct_index": 0}))
        self.assertFalse(_valid_shape({"question": "q", "options": ["a", "b", "c", "d"], "correct_index": 4}))
        self.assertFalse(_valid_shape({"question": "", "options": ["a", "b", "c", "d"], "correct_index": 0}))

    def test_rejects_bool_correct_index(self):
        # True is an int subclass — must not pass as a valid index.
        self.assertFalse(_valid_shape({"question": "q", "options": ["a", "b", "c", "d"], "correct_index": True}))


class LeakageTest(unittest.TestCase):
    def test_detects_verbatim_span(self):
        source = _norm_words("structured concurrency ensures that coroutines launched in a scope complete")
        # Shares a >= 8-word consecutive run → flagged as copied.
        self.assertTrue(_has_verbatim_span(
            "structured concurrency ensures that coroutines launched in a scope before returns", source))
        # Only a short overlap / reworded → not flagged.
        self.assertFalse(_has_verbatim_span("what does structured concurrency guarantee for you", source))


class TopicTest(unittest.TestCase):
    def test_maps_to_generic_topic_no_source_identity(self):
        self.assertEqual(_topic_for("kotlin-coroutines.md"), "coroutines")
        self.assertEqual(_topic_for("compose-internals.md"), "compose")
        self.assertEqual(_topic_for("effective-kotlin.md"), "kotlin")
        self.assertEqual(_topic_for("something-else.md"), "android")


class BuildPoolTest(unittest.TestCase):
    def _records(self, n=5):
        long = "structured concurrency and coroutine scopes " * 20  # > min chars
        return [{"text": long, "metadata": {"filename": "kotlin-coroutines.md"}} for _ in range(n)]

    def test_generates_validated_pool(self):
        replies = iter([_mcq_json(question=f"Q{i}") for i in range(5)])
        pool = build_pool(self._records(5), lambda m, p: next(replies), count=5, seed=1)
        self.assertEqual(len(pool), 5)
        self.assertTrue(all(isinstance(m, MCQ) and m.topic == "coroutines" for m in pool))
        self.assertTrue(all(len(m.options) == 4 for m in pool))

    def test_skips_short_chunks(self):
        recs = [{"text": "too short", "metadata": {}}]
        pool = build_pool(recs, lambda m, p: _mcq_json(), count=5)
        self.assertEqual(pool, [])

    def test_retries_once_then_drops_bad(self):
        # First call returns junk, retry returns valid → 1 MCQ from 1 usable chunk.
        seq = iter(["garbage", _mcq_json()])
        pool = build_pool(self._records(1), lambda m, p: next(seq), count=5, seed=1)
        self.assertEqual(len(pool), 1)

    def test_dedupes_identical_questions(self):
        pool = build_pool(self._records(3), lambda m, p: _mcq_json(question="Same?"), count=3, seed=1)
        self.assertEqual(len(pool), 1)

    def test_rejects_leaky_generation(self):
        # The model copies a long verbatim span from the chunk → dropped.
        leaked = _mcq_json(question="structured concurrency and coroutine scopes structured concurrency and coroutine scopes")
        pool = build_pool(self._records(1), lambda m, p: leaked, count=5, seed=1)
        self.assertEqual(pool, [])


class ValidatePoolTest(unittest.TestCase):
    def test_accepts_good_pool(self):
        good = [{"id": "q1", "topic": "coroutines", "question": "q",
                 "options": ["a", "b", "c", "d"], "correct_index": 0}]
        self.assertEqual(validate_pool(good), [])

    def test_reports_problems(self):
        self.assertTrue(validate_pool([]))
        bad = [{"id": "q1", "topic": "t", "question": "q", "options": ["a", "b"], "correct_index": 0}]
        self.assertTrue(validate_pool(bad))

    def test_roundtrip_json(self):
        pool = [MCQ("q1", "coroutines", "q", ["a", "b", "c", "d"], 2)]
        self.assertEqual(validate_pool(json.loads(mcqs_to_json(pool))), [])


if __name__ == "__main__":
    unittest.main()
