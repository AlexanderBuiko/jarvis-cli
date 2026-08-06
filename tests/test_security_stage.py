"""Tests for the security-review FSM stage (jarvis.pipeline.stages.SecurityAgent).

The security stage is the Day-14 gate between validation and commit. These pin the
marker-to-verdict contract: a Critical/High finding recommends a rework, Medium/Low
proceeds, and the stage cannot run without an executed deliverable to inspect.
"""

import unittest

from jarvis.pipeline.base import (
    GATE_APPROVAL,
    MARKER_SECURITY_FAIL,
    MARKER_SECURITY_WARN,
)
from jarvis.pipeline.stages import SecurityAgent


def _reviewed_task() -> dict:
    return {"stage": "security", "stage_outputs": {"execution": "def f(): ..."}}


class SecurityAgentTest(unittest.TestCase):
    def test_critical_or_high_recommends_rework_to_execution(self):
        task = _reviewed_task()
        v = SecurityAgent().process(task, "Hardcoded token, Critical.\n" + MARKER_SECURITY_FAIL)
        self.assertEqual(v.gate, GATE_APPROVAL)
        self.assertEqual(v.confirm_target, "done")
        self.assertEqual(v.reject_target, "execution")
        self.assertTrue(v.fail_recommended)
        self.assertEqual(task["expected_action"], "await_security_approval")

    def test_medium_or_low_proceeds_with_no_rework_recommended(self):
        v = SecurityAgent().process(_reviewed_task(), "Weak default, Low.\n" + MARKER_SECURITY_WARN)
        self.assertEqual(v.gate, GATE_APPROVAL)
        self.assertEqual(v.confirm_target, "done")
        self.assertFalse(v.fail_recommended)

    def test_clean_review_proceeds_to_done(self):
        v = SecurityAgent().process(_reviewed_task(), "No security-relevant code. CLEAN.")
        self.assertEqual(v.confirm_target, "done")
        self.assertFalse(v.fail_recommended)

    def test_stage_blocks_without_an_executed_deliverable(self):
        ok, reason = SecurityAgent().input_ready({"stage": "security", "stage_outputs": {}})
        self.assertFalse(ok)
        self.assertIn("deliverable", reason)

    def test_findings_are_persisted_for_the_rework_feedback(self):
        task = _reviewed_task()
        SecurityAgent().process(task, "SQL injection at line 42, High.\n" + MARKER_SECURITY_FAIL)
        self.assertIn("SQL injection", task["stage_outputs"]["security"])


if __name__ == "__main__":
    unittest.main()
