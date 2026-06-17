"""Tests for the per-stage agents, marker parsing, and stage I/O contracts."""

import unittest

from jarvis.pipeline.base import (
    MARKER_FAIL,
    MARKER_NEEDS_USER,
    MARKER_PASS,
    MARKER_READY,
    MARKER_REPLAN,
    parse_markers,
)
from jarvis.pipeline.stages import (
    ClarifierAgent,
    ExecutorAgent,
    PlannerAgent,
    ValidatorAgent,
    STAGE_AGENTS,
    stage_system_fragment,
)
from jarvis.prompt_builder.builder import build_system_prompt


class ParseMarkersTest(unittest.TestCase):
    def test_strips_marker_and_reports_it(self):
        clean, found = parse_markers("Here is the plan.\n" + MARKER_READY)
        self.assertEqual(clean, "Here is the plan.")
        self.assertEqual(found, {MARKER_READY})

    def test_no_marker(self):
        clean, found = parse_markers("just text")
        self.assertEqual(clean, "just text")
        self.assertEqual(found, set())


class ClarifierTest(unittest.TestCase):
    def test_ready_marker_advances(self):
        task = {"stage": "clarification"}
        v = ClarifierAgent().process(task, "I understand the task.\n" + MARKER_READY)
        self.assertTrue(v.ready)
        self.assertFalse(v.needs_user)
        self.assertEqual(task["expected_action"], "ready_to_plan")
        self.assertEqual(task["description"], "I understand the task.")

    def test_no_marker_is_a_user_gate(self):
        task = {"stage": "clarification"}
        v = ClarifierAgent().process(task, "Which database should I use?")
        self.assertTrue(v.needs_user)
        self.assertFalse(v.ready)
        self.assertEqual(task["expected_action"], "await_user")


class PlannerTest(unittest.TestCase):
    def test_input_contract_requires_description(self):
        ok, _ = PlannerAgent().input_ready({"stage": "planning"})
        self.assertFalse(ok)
        ok, _ = PlannerAgent().input_ready({"stage": "planning", "description": "x"})
        self.assertTrue(ok)

    def test_ready_records_plan(self):
        task = {"stage": "planning", "description": "x"}
        v = PlannerAgent().process(task, "1. do a\n2. do b\n" + MARKER_READY)
        self.assertTrue(v.ready)
        self.assertEqual(task["plan"], "1. do a\n2. do b")
        self.assertEqual(task["expected_action"], "ready_to_execute")


class ExecutorTest(unittest.TestCase):
    def test_input_contract_requires_plan(self):
        ok, _ = ExecutorAgent().input_ready({"stage": "execution"})
        self.assertFalse(ok)
        ok, _ = ExecutorAgent().input_ready({"stage": "execution", "plan": "p"})
        self.assertTrue(ok)

    def test_ready_sets_current_step_and_advances(self):
        task = {"stage": "execution", "plan": "p"}
        v = ExecutorAgent().process(task, "Working on step one now.\nDetails...\n" + MARKER_READY)
        self.assertTrue(v.ready)
        self.assertEqual(task["current_step"], "Working on step one now.")
        self.assertEqual(task["expected_action"], "ready_to_validate")

    def test_needs_user_gate(self):
        task = {"stage": "execution", "plan": "p"}
        v = ExecutorAgent().process(task, "What's your answer?\n" + MARKER_NEEDS_USER)
        self.assertTrue(v.needs_user)
        self.assertFalse(v.ready)

    def test_replan_is_a_backward_gate(self):
        task = {"stage": "execution", "plan": "p"}
        v = ExecutorAgent().process(task, "The plan is wrong.\n" + MARKER_REPLAN)
        self.assertTrue(v.needs_user)
        self.assertEqual(v.next_target, "planning")
        self.assertEqual(task["expected_action"], "needs_replan")


class ValidatorTest(unittest.TestCase):
    def test_pass_advances_to_done(self):
        task = {"stage": "validation", "plan": "p"}
        v = ValidatorAgent().process(task, "All criteria met.\n" + MARKER_PASS)
        self.assertTrue(v.ready)
        self.assertEqual(v.next_target, "done")
        self.assertEqual(task["expected_action"], "ready_to_finish")

    def test_fail_is_a_backward_gate(self):
        task = {"stage": "validation", "plan": "p"}
        v = ValidatorAgent().process(task, "Missing error handling.\n" + MARKER_FAIL)
        self.assertTrue(v.needs_user)
        self.assertEqual(v.next_target, "execution")
        self.assertEqual(task["expected_action"], "needs_rework")


class RegistryTest(unittest.TestCase):
    def test_every_stage_has_an_agent(self):
        for stage in ("clarification", "planning", "execution", "validation", "done"):
            self.assertIn(stage, STAGE_AGENTS)

    def test_build_system_prompt_uses_stage_fragment(self):
        task = {"stage": "planning", "description": "x"}
        prompt = build_system_prompt({}, task=task)
        self.assertIn("PLANNING stage", prompt)
        # The fragment came from the registry, matching the agent's own text.
        self.assertIn(stage_system_fragment("planning", task)[:30], prompt)


if __name__ == "__main__":
    unittest.main()
