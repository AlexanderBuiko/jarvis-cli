"""Tests for the Orchestrator.step() primitive driving the task FSM."""

import tempfile
import unittest
from pathlib import Path

from jarvis.pipeline.base import GATE_APPROVAL, GATE_QUESTION, MARKER_READY, MARKER_STEP_DONE
from jarvis.pipeline.orchestrator import Orchestrator
from jarvis.pipeline.stages import STAGE_AGENTS
from jarvis.session.task_store import TaskStore


class _FakeRunner:
    """A StageRunner stand-in: delegates to a per-test fn(task, entry, extra)->str."""

    def __init__(self, fn=None):
        self.fn = fn

    def run(self, task, entry_message, extra_system=""):
        return self.fn(task, entry_message, extra_system)


class OrchestratorStepTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tasks = TaskStore(Path(self._tmp.name))
        self.runner = _FakeRunner()
        self.orch = Orchestrator(STAGE_AGENTS, self.tasks, self.runner)

    def tearDown(self):
        self._tmp.cleanup()

    def _returns(self, text):
        """Set the runner to return a fixed text for the next step."""
        self.runner.fn = lambda task, entry, extra: text

    def test_clarification_ready_auto_advances_to_planning(self):
        task = self.tasks.new_task("demo")  # clarification
        self._returns("Understood.\n" + MARKER_READY)
        result = self.orch.step(task)
        self.assertEqual(result.advanced_to, "planning")
        self.assertEqual(task["stage"], "planning")

    def test_clarification_question_is_a_gate(self):
        task = self.tasks.new_task("demo")
        self._returns("Which DB?")
        result = self.orch.step(task)
        self.assertEqual(result.verdict.gate, GATE_QUESTION)
        self.assertIsNone(result.advanced_to)
        self.assertEqual(task["stage"], "clarification")

    def test_planning_stops_at_approval_gate(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "planning"
        task["description"] = "x"
        self._returns("1. a\n2. b")
        result = self.orch.step(task)
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
        self._returns("did a\n" + MARKER_STEP_DONE)
        result = self.orch.step(task)
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
        self._returns("done\n" + MARKER_READY)
        result = self.orch.step(task)
        self.assertEqual(result.advanced_to, "validation")
        self.assertEqual(task["stage"], "validation")

    def test_validation_stops_at_approval_gate(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "validation"
        task["plan"] = "p"
        self._returns("Looks good.")
        result = self.orch.step(task)
        self.assertEqual(result.verdict.gate, GATE_APPROVAL)
        self.assertEqual(result.verdict.confirm_target, "done")
        self.assertEqual(task["stage"], "validation")

    def test_blocked_input_contract(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "execution"  # no plan
        called = []
        self.runner.fn = lambda task, entry, extra: called.append(1) or "x"
        result = self.orch.step(task)
        self.assertIsNotNone(result.blocked)
        self.assertEqual(called, [])  # the model was never called

    def test_extra_instruction_appended_to_entry(self):
        task = self.tasks.new_task("demo")
        seen = {}

        def fn(task, entry, extra):
            seen["entry"] = entry
            return "ok\n" + MARKER_READY

        self.runner.fn = fn
        self.orch.step(task, extra_instruction="The user responded: postgres")
        self.assertIn("postgres", seen["entry"])


if __name__ == "__main__":
    unittest.main()
