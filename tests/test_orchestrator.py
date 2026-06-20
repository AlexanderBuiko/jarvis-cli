"""Tests for the Orchestrator.step() primitive driving the task FSM."""

import tempfile
import unittest
from pathlib import Path

from jarvis.pipeline.base import GATE_APPROVAL, GATE_QUESTION, MARKER_READY, MARKER_STEP_DONE
from jarvis.pipeline.orchestrator import Orchestrator
from jarvis.pipeline.stages import STAGE_AGENTS
from jarvis.session.task_store import TaskStore


class OrchestratorStepTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tasks = TaskStore(Path(self._tmp.name))
        self.orch = Orchestrator(STAGE_AGENTS, self.tasks)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_turn_returning(self, task, scripts: dict[str, str]):
        def run_turn(entry, extra_system):
            return scripts[task["stage"]]
        return run_turn

    def test_clarification_ready_auto_advances_to_planning(self):
        task = self.tasks.new_task("demo")  # clarification
        result = self.orch.step(task, lambda e, x: "Understood.\n" + MARKER_READY)
        self.assertEqual(result.advanced_to, "planning")
        self.assertEqual(task["stage"], "planning")

    def test_clarification_question_is_a_gate(self):
        task = self.tasks.new_task("demo")
        result = self.orch.step(task, lambda e, x: "Which DB?")
        self.assertEqual(result.verdict.gate, GATE_QUESTION)
        self.assertIsNone(result.advanced_to)
        self.assertEqual(task["stage"], "clarification")

    def test_planning_stops_at_approval_gate(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "planning"
        task["description"] = "x"
        result = self.orch.step(task, lambda e, x: "1. a\n2. b")
        self.assertEqual(result.verdict.gate, GATE_APPROVAL)
        self.assertIsNone(result.advanced_to)        # does NOT auto-advance
        self.assertEqual(task["stage"], "planning")
        self.assertEqual(task["plan_steps"], ["a", "b"])

    def test_execution_step_done_stays_in_stage(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "execution"
        task["plan"] = "1. a\n2. b"
        task["plan_steps"] = ["a", "b"]
        task["step_index"] = 0
        result = self.orch.step(task, lambda e, x: "did a\n" + MARKER_STEP_DONE)
        self.assertTrue(result.verdict.continue_stage)
        self.assertIsNone(result.advanced_to)
        self.assertEqual(task["stage"], "execution")
        self.assertEqual(task["step_index"], 1)

    def test_execution_ready_auto_advances_to_validation(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "execution"
        task["plan"] = "1. a"
        task["plan_steps"] = ["a"]
        task["step_index"] = 0
        result = self.orch.step(task, lambda e, x: "done\n" + MARKER_READY)
        self.assertEqual(result.advanced_to, "validation")
        self.assertEqual(task["stage"], "validation")

    def test_validation_stops_at_approval_gate(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "validation"
        task["plan"] = "p"
        result = self.orch.step(task, lambda e, x: "Looks good.")
        self.assertEqual(result.verdict.gate, GATE_APPROVAL)
        self.assertEqual(result.verdict.confirm_target, "done")
        self.assertEqual(task["stage"], "validation")

    def test_blocked_input_contract(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "execution"  # no plan
        called = []
        result = self.orch.step(task, lambda e, x: called.append(1) or "x")
        self.assertIsNotNone(result.blocked)
        self.assertEqual(called, [])  # the model was never called

    def test_extra_instruction_appended_to_entry(self):
        task = self.tasks.new_task("demo")
        seen = {}

        def run_turn(entry, extra_system):
            seen["entry"] = entry
            return "ok\n" + MARKER_READY

        self.orch.step(task, run_turn, extra_instruction="The user responded: postgres")
        self.assertIn("postgres", seen["entry"])


if __name__ == "__main__":
    unittest.main()
