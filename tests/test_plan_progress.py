"""Tests for the plan-progress step table (completed / in-progress / pending)."""

import unittest

from jarvis.repl.commands import render_plan_progress


class RenderPlanProgressTest(unittest.TestCase):
    def test_none_without_steps(self):
        self.assertIsNone(render_plan_progress({"plan_steps": []}))

    def test_marks_completed_current_pending(self):
        task = {"plan_steps": ["a", "b", "c"], "step_index": 1}
        out = render_plan_progress(task)
        self.assertEqual(
            out.splitlines(),
            ["Steps (1/3 done)", "  ✓  1. a", "  ▶  2. b", "  ○  3. c"],
        )

    def test_all_done(self):
        task = {"plan_steps": ["a", "b"], "step_index": 2}
        out = render_plan_progress(task)
        self.assertEqual(out.splitlines(), ["Steps (2/2 done)", "  ✓  1. a", "  ✓  2. b"])

    def test_first_step_in_progress(self):
        task = {"plan_steps": ["a", "b"], "step_index": 0}
        out = render_plan_progress(task)
        self.assertEqual(out.splitlines(), ["Steps (0/2 done)", "  ▶  1. a", "  ○  2. b"])


if __name__ == "__main__":
    unittest.main()
