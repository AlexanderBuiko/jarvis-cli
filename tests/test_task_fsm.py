"""Tests for the task FSM policy (jarvis.pipeline.fsm).

Pure policy, no persistence and no network — this is the code-level guard that
makes "the assistant cannot skip a stage" real, so it is worth pinning directly.
"""

import unittest

from jarvis.pipeline.fsm import (
    STAGES,
    ALLOWED_TRANSITIONS,
    default_target,
    is_allowed,
    resolve_transition,
)


class StagesTest(unittest.TestCase):
    def test_the_five_canonical_stages_are_in_order(self):
        self.assertEqual(
            STAGES,
            ("clarification", "planning", "execution", "validation", "done"),
        )

    def test_every_stage_has_a_transition_entry(self):
        self.assertEqual(set(ALLOWED_TRANSITIONS), set(STAGES))


class DefaultTargetTest(unittest.TestCase):
    def test_forward_edge_is_the_first_listed_target(self):
        self.assertEqual(default_target("clarification"), "planning")
        self.assertEqual(default_target("execution"), "validation")

    def test_terminal_stage_has_no_default_target(self):
        self.assertIsNone(default_target("done"))

    def test_unknown_stage_has_no_default_target(self):
        self.assertIsNone(default_target("nonsense"))


class IsAllowedTest(unittest.TestCase):
    def test_permitted_forward_transition_is_allowed(self):
        self.assertTrue(is_allowed("clarification", "planning"))

    def test_permitted_backward_transition_is_allowed(self):
        self.assertTrue(is_allowed("execution", "planning"))

    def test_skipping_a_stage_is_not_allowed(self):
        self.assertFalse(is_allowed("clarification", "execution"))

    def test_transition_from_unknown_stage_is_not_allowed(self):
        self.assertFalse(is_allowed("nonsense", "planning"))


class ResolveTransitionTest(unittest.TestCase):
    def test_omitted_target_resolves_to_the_forward_edge(self):
        self.assertEqual(resolve_transition("planning", None), "execution")

    def test_explicit_permitted_target_is_returned_unchanged(self):
        self.assertEqual(resolve_transition("validation", "execution"), "execution")

    def test_terminal_stage_raises(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_transition("done", None)
        self.assertIn("terminal", str(ctx.exception))

    def test_illegal_transition_raises_and_lists_the_allowed_targets(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_transition("clarification", "done")
        message = str(ctx.exception)
        self.assertIn("clarification", message)
        self.assertIn("planning", message)


if __name__ == "__main__":
    unittest.main()
