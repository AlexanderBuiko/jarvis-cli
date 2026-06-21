"""Tests for thread-locked config params and the task approval-gate choices."""

import unittest

from jarvis.pipeline.stages import ValidatorAgent
from jarvis.repl.loop import _changed_keys, _locked_param_error, _approval_choices


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


class ApprovalChoicesTest(unittest.TestCase):
    """The validation gate must let the user pick 'revise the plan' directly."""

    def test_validation_has_three_choices_with_correct_targets(self):
        v = ValidatorAgent().process({"stage": "validation", "plan": "p"}, "findings")
        title, choices = _approval_choices("validation", v)
        targets = [t for _, t in choices]
        self.assertEqual(targets, ["done", "execution", "planning"])
        # The third option re-plans — the path that was previously unreachable.
        self.assertIn("revise the plan", choices[2][0].lower())

    def test_recommended_annotation_when_validator_flags_plan(self):
        from jarvis.pipeline.base import MARKER_REPLAN
        v = ValidatorAgent().process({"stage": "validation", "plan": "p"}, "bad plan\n" + MARKER_REPLAN)
        _, choices = _approval_choices("validation", v)
        self.assertIn("recommended", choices[2][0].lower())

    def test_planning_gate_has_two_choices(self):
        from jarvis.pipeline.stages import PlannerAgent
        v = PlannerAgent().process({"stage": "planning", "description": "x"}, "1. a\n2. b")
        _, choices = _approval_choices("planning", v)
        targets = [t for _, t in choices]
        self.assertEqual(targets, ["execution", "planning"])


if __name__ == "__main__":
    unittest.main()
