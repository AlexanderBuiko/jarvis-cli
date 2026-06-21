"""Tests for the task finite state machine and persisted state."""

import tempfile
import unittest
from pathlib import Path

from jarvis.session.task_store import TaskStore, ALLOWED_TRANSITIONS


class TaskStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_new_task_has_fsm_fields(self):
        task = self.store.new_task("demo")
        self.assertEqual(task["stage"], "clarification")
        self.assertEqual(task["current_step"], "")
        self.assertEqual(task["expected_action"], "")

    def test_forward_path(self):
        task = self.store.new_task("demo")
        self.assertEqual(self.store.advance_stage(task), "planning")
        self.assertEqual(self.store.advance_stage(task), "execution")
        self.assertEqual(self.store.advance_stage(task), "validation")
        self.assertEqual(self.store.advance_stage(task), "done")

    def test_execution_can_return_to_planning(self):
        task = self.store.new_task("demo")
        self.store.advance_stage(task)  # planning
        self.store.advance_stage(task)  # execution
        self.assertEqual(self.store.advance_stage(task, "planning"), "planning")

    def test_validation_can_return_to_execution(self):
        task = self.store.new_task("demo")
        for _ in range(3):
            self.store.advance_stage(task)  # -> validation
        self.assertEqual(task["stage"], "validation")
        self.assertEqual(self.store.advance_stage(task, "execution"), "execution")

    def test_illegal_transition_rejected(self):
        task = self.store.new_task("demo")  # clarification
        with self.assertRaises(ValueError):
            self.store.advance_stage(task, "done")

    def test_terminal_stage_cannot_advance(self):
        task = self.store.new_task("demo")
        for _ in range(4):
            self.store.advance_stage(task)  # -> done
        self.assertEqual(task["stage"], "done")
        with self.assertRaises(ValueError):
            self.store.advance_stage(task)

    def test_advance_clears_current_step(self):
        task = self.store.new_task("demo")
        task["current_step"] = "doing the thing"
        self.store.advance_stage(task)
        self.assertEqual(task["current_step"], "")

    def test_old_files_get_field_defaults(self):
        # Simulate a task file written before the new fields existed.
        import json
        path = Path(self._tmp.name) / "legacy01.json"
        path.write_text(json.dumps({"id": "legacy01", "stage": "planning"}), encoding="utf-8")
        loaded = self.store.load("legacy01")
        self.assertEqual(loaded["current_step"], "")
        self.assertEqual(loaded["expected_action"], "")

    def test_save_result_writes_artifact_and_records_path(self):
        task = self.store.new_task("demo")
        path = self.store.save_result(task, "# Deliverable\nthe final result")
        self.assertTrue(path.exists())
        self.assertEqual(path.parent.name, "results")  # stored under tasks/results/
        self.assertEqual(path.read_text(encoding="utf-8"), "# Deliverable\nthe final result")
        self.assertEqual(task["result_path"], str(path))
        # Persisted to the task file too.
        self.assertEqual(self.store.load(task["id"])["result_path"], str(path))

    def test_new_task_has_result_fields(self):
        task = self.store.new_task("demo")
        self.assertEqual(task["plan_steps"], [])
        self.assertEqual(task["step_index"], 0)
        self.assertEqual(task["result_path"], "")

    def test_allowed_transitions_shape(self):
        # The execution -> planning revision edge from the tutor's KB is present.
        self.assertIn("planning", ALLOWED_TRANSITIONS["execution"])
        self.assertEqual(ALLOWED_TRANSITIONS["execution"][0], "validation")

    def test_validation_can_return_to_planning(self):
        # Validation may re-plan directly when the plan itself is at fault.
        task = self.store.new_task("demo")
        for _ in range(3):
            self.store.advance_stage(task)  # -> validation
        self.assertEqual(task["stage"], "validation")
        self.assertEqual(self.store.advance_stage(task, "planning"), "planning")

    def test_new_task_has_accounting_fields(self):
        task = self.store.new_task("demo")
        self.assertEqual(task["api_call_count"], 0)
        self.assertEqual(task["total_tokens"], 0)
        self.assertEqual(task["total_cost"], 0.0)


if __name__ == "__main__":
    unittest.main()
