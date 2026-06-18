"""Tests for the per-stage agents, marker parsing, and stage I/O contracts."""

import unittest

from jarvis.pipeline.base import (
    MARKER_FAIL,
    MARKER_NEEDS_USER,
    MARKER_PASS,
    MARKER_READY,
    MARKER_REPLAN,
    MARKER_STEP_DONE,
    parse_markers,
)
from jarvis.pipeline.stages import (
    ClarifierAgent,
    ExecutorAgent,
    PlannerAgent,
    ValidatorAgent,
    STAGE_AGENTS,
    parse_plan_steps,
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

    def test_ready_records_and_parses_plan(self):
        task = {"stage": "planning", "description": "x"}
        v = PlannerAgent().process(task, "1. do a\n2. do b\n" + MARKER_READY)
        self.assertTrue(v.ready)
        self.assertEqual(task["plan"], "1. do a\n2. do b")
        self.assertEqual(task["plan_steps"], ["do a", "do b"])
        self.assertEqual(task["step_index"], 0)
        self.assertEqual(task["expected_action"], "ready_to_execute")


class ParsePlanStepsTest(unittest.TestCase):
    def test_numbered(self):
        self.assertEqual(parse_plan_steps("1. a\n2) b\n3. c"), ["a", "b", "c"])

    def test_bulleted(self):
        self.assertEqual(parse_plan_steps("- a\n* b\n• c"), ["a", "b", "c"])

    def test_fallback_to_lines(self):
        self.assertEqual(parse_plan_steps("do a\ndo b"), ["do a", "do b"])


class ExecutorTest(unittest.TestCase):
    def _task(self):
        return {"stage": "execution", "plan": "p", "plan_steps": ["a", "b", "c"], "step_index": 0}

    def test_input_contract_requires_plan(self):
        ok, _ = ExecutorAgent().input_ready({"stage": "execution"})
        self.assertFalse(ok)
        ok, _ = ExecutorAgent().input_ready({"stage": "execution", "plan": "p"})
        self.assertTrue(ok)

    def test_step_done_advances_one_step_and_continues(self):
        task = self._task()
        v = ExecutorAgent().process(task, "Did step a.\n" + MARKER_STEP_DONE)
        self.assertTrue(v.continue_stage)
        self.assertFalse(v.ready)
        self.assertFalse(v.needs_user)
        self.assertEqual(task["step_index"], 1)
        self.assertEqual(task["current_step"], "b")

    def test_ready_marks_all_steps_done(self):
        task = self._task()
        task["step_index"] = 2
        v = ExecutorAgent().process(task, "Final step done.\n" + MARKER_READY)
        self.assertTrue(v.ready)
        self.assertEqual(task["step_index"], 3)  # == len(steps): all complete
        self.assertEqual(task["current_step"], "")
        self.assertEqual(task["expected_action"], "ready_to_validate")

    def test_entry_message_names_current_step(self):
        task = self._task()
        task["step_index"] = 1
        msg = ExecutorAgent().entry_message(task)
        self.assertIn("step 2 of 3", msg)
        self.assertIn("b", msg)

    def test_needs_user_gate(self):
        v = ExecutorAgent().process(self._task(), "What's your answer?\n" + MARKER_NEEDS_USER)
        self.assertTrue(v.needs_user)
        self.assertFalse(v.ready)

    def test_replan_is_a_backward_gate(self):
        task = self._task()
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
