"""Tests for thread-locked config params (model, context_strategy)."""

import unittest

from jarvis.repl.loop import _changed_keys, _locked_param_error


class _Agent:
    def __init__(self, history):
        self.history = history


class ChangedKeysTest(unittest.TestCase):
    def test_set(self):
        self.assertEqual(_changed_keys("set", ["model", "x/y"]), {"model"})
        self.assertEqual(_changed_keys("set", []), set())

    def test_update(self):
        self.assertEqual(
            _changed_keys("update", ["model=x", "temperature=0.5"]),
            {"model", "temperature"},
        )


class LockedParamTest(unittest.TestCase):
    def test_model_locked_on_nonempty_thread(self):
        err = _locked_param_error("set", ["model", "x/y"], _Agent(["turn"]))
        self.assertIsNotNone(err)
        self.assertIn("model", err)

    def test_context_strategy_locked_on_nonempty_thread(self):
        err = _locked_param_error("update", ["context_strategy=topics"], _Agent(["turn"]))
        self.assertIsNotNone(err)
        self.assertIn("context_strategy", err)

    def test_empty_thread_allows_change(self):
        self.assertIsNone(_locked_param_error("set", ["model", "x/y"], _Agent([])))

    def test_unlocked_param_allowed(self):
        self.assertIsNone(_locked_param_error("set", ["temperature", "0.5"], _Agent(["turn"])))


if __name__ == "__main__":
    unittest.main()
