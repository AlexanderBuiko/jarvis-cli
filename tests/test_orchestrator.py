"""Tests for the Orchestrator driving the task FSM across stage agents."""

import tempfile
import unittest
from pathlib import Path

from jarvis.pipeline.base import (
    MARKER_FAIL,
    MARKER_NEEDS_USER,
    MARKER_PASS,
    MARKER_READY,
    MARKER_STEP_DONE,
)
from jarvis.pipeline.orchestrator import Orchestrator
from jarvis.pipeline.stages import STAGE_AGENTS
from jarvis.session.task_store import TaskStore


class OrchestratorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tasks = TaskStore(Path(self._tmp.name))
        self.orch = Orchestrator(STAGE_AGENTS, self.tasks)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_turn_for(self, task, scripts: dict[str, str]):
        """Build a run_turn that answers based on the task's current stage."""
        calls: list[str] = []

        def run_turn(entry: str, extra_system: str) -> str:
            calls.append(task["stage"])
            return scripts[task["stage"]]

        run_turn.calls = calls  # type: ignore[attr-defined]
        return run_turn

    def test_full_forward_pipeline_runs_to_done(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "planning"
        task["description"] = "build a thing"
        scripts = {
            "planning": "1. a\n2. b\n" + MARKER_READY,
            "execution": "did the work\n" + MARKER_READY,
            "validation": "all good\n" + MARKER_PASS,
        }
        results = self.orch.run(task, self._run_turn_for(task, scripts), autonomy="auto")

        self.assertEqual([r.stage for r in results], ["planning", "execution", "validation"])
        self.assertEqual([r.advanced_to for r in results], ["execution", "validation", "done"])
        self.assertEqual(task["stage"], "done")
        self.assertEqual(task["plan"], "1. a\n2. b")

    def test_stepwise_execution_loops_until_ready(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "execution"
        task["plan"] = "1. a\n2. b\n3. c"
        task["plan_steps"] = ["a", "b", "c"]
        task["step_index"] = 0

        # Two steps report STEP_DONE, the third reports READY; validation passes.
        exec_replies = iter([
            "did a\n" + MARKER_STEP_DONE,
            "did b\n" + MARKER_STEP_DONE,
            "did c\n" + MARKER_READY,
        ])

        def run_turn(entry, extra_system):
            if task["stage"] == "execution":
                return next(exec_replies)
            return "all good\n" + MARKER_PASS

        results = self.orch.run(task, run_turn, autonomy="auto")
        exec_results = [r for r in results if r.stage == "execution"]
        self.assertEqual(len(exec_results), 3)   # one turn per step
        self.assertEqual(task["step_index"], 3)  # all steps complete
        self.assertEqual(task["stage"], "done")  # rolled through validation -> done

    def test_stepwise_execution_manual_runs_one_step(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "execution"
        task["plan_steps"] = ["a", "b"]
        task["plan"] = "1. a\n2. b"
        task["step_index"] = 0
        results = self.orch.run(task, lambda e, x: "did a\n" + MARKER_STEP_DONE, autonomy="manual")
        self.assertEqual(len(results), 1)
        self.assertEqual(task["step_index"], 1)
        self.assertEqual(task["stage"], "execution")  # manual: no auto-continue

    def test_clarification_is_a_gate(self):
        task = self.tasks.new_task("demo")  # clarification
        scripts = {"clarification": "Which DB?\n" + MARKER_NEEDS_USER}
        results = self.orch.run(task, self._run_turn_for(task, scripts), autonomy="auto")

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].verdict.needs_user)
        self.assertIsNone(results[0].advanced_to)
        self.assertEqual(task["stage"], "clarification")

    def test_validation_failure_stops_without_looping(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "validation"
        task["plan"] = "p"
        scripts = {"validation": "missing tests\n" + MARKER_FAIL}
        results = self.orch.run(task, self._run_turn_for(task, scripts), autonomy="auto")

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].verdict.needs_user)
        self.assertEqual(task["stage"], "validation")  # did NOT auto-advance
        self.assertEqual(task["expected_action"], "needs_rework")

    def test_manual_autonomy_runs_single_stage(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "planning"
        task["description"] = "x"
        scripts = {"planning": "plan\n" + MARKER_READY}
        results = self.orch.run(task, self._run_turn_for(task, scripts), autonomy="manual")

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].advanced_to)
        self.assertEqual(task["stage"], "planning")  # ready, but manual => no advance

    def test_input_contract_blocks_before_any_call(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "execution"  # no plan present
        run_turn = self._run_turn_for(task, {})
        results = self.orch.run(task, run_turn, autonomy="auto")

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].blocked)
        self.assertEqual(run_turn.calls, [])  # the LLM was never called

    def test_done_task_does_nothing(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "done"
        results = self.orch.run(task, self._run_turn_for(task, {}), autonomy="auto")
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
