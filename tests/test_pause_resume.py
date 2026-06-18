"""
Integration tests for pause/resume behaviour against the real JarvisAgent.

$HOME points at a temp dir so all of ~/.jarvis (threads, tasks, sessions, memory)
is isolated per test. The pipeline is driven via agent.pipeline_step() +
agent.advance_to() — the same primitives the interactive driver uses.
"""

import os
import tempfile
import unittest

from jarvis.agent import JarvisAgent
from jarvis.config.manager import ConfigManager
from jarvis.pipeline.base import GATE_APPROVAL
from tests.fake_engine import FakeEngine

PLAN = "1. build the thing\n2. test the thing"


def _responder(messages, params):
    """Stage-aware fake replies keyed on the entry/last message."""
    last = messages[-1]["content"]
    if "enough to write a plan" in last:          # clarifier entry
        return "Understood the task.\n[[READY]]"
    if "Produce the concrete" in last:            # planner entry
        return PLAN                               # no marker -> approval gate
    if "Work on step 1" in last:                  # first execution step
        return "Built it.\n[[STEP_DONE]]"
    if "Work on step" in last:                    # later execution step
        return "Need your input.\n[[NEEDS_USER]]"
    return "ok"


class PauseResumeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name

    def tearDown(self):
        if self._old_home is not None:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def _agent(self, responder=None):
        engine = FakeEngine(responder=responder)
        return engine, JarvisAgent(engine, ConfigManager())

    def _drive_into_execution(self, agent):
        """clarification -> planning -> (confirm plan) -> execution (one step done)."""
        agent.pipeline_step()                         # clarification READY -> planning
        r = agent.pipeline_step()                     # planning -> approval gate
        self.assertEqual(r.verdict.gate, GATE_APPROVAL)
        agent.advance_to(r.verdict.confirm_target)    # Confirm -> execution
        agent.pipeline_step()                         # execution step 1 -> STEP_DONE

    def test_pause_at_execution_preserves_state(self):
        _, agent = self._agent(_responder)
        agent.create_task("demo")
        self._drive_into_execution(agent)

        self.assertEqual(agent.active_task["stage"], "execution")
        self.assertIn("build the thing", agent.active_task["plan"])
        self.assertEqual(agent.active_task["step_index"], 1)

        self.assertEqual(agent.pause_task(), "demo")
        self.assertIsNone(agent.active_task)

        task = agent._tasks.find("demo")
        self.assertEqual(task["stage"], "execution")
        self.assertIn("build the thing", task["plan"])
        self.assertEqual(task["step_index"], 1)  # progress persisted

    def test_resume_continues_from_saved_step_without_re_explaining(self):
        engine, agent = self._agent(_responder)
        agent.create_task("demo")
        self._drive_into_execution(agent)   # step_index now 1
        agent.pause_task()

        # Brand-new, empty thread.
        agent.new_thread("fresh")
        self.assertEqual(agent.history, [])
        self.assertTrue(agent.start_task("demo"))

        # The executor's next entry message targets step 2 (resumes, not restarts).
        from jarvis.pipeline.stages import ExecutorAgent
        entry = ExecutorAgent().entry_message(agent.active_task)
        self.assertIn("step 2 of 2", entry)

        # And the plan reached the model via the working-memory block, not history.
        engine.responder = lambda m, p: "We are mid-execution.\n[[NEEDS_USER]]"
        agent.pipeline_step()
        sent = engine.calls[-1][0]
        blob = "\n".join(m["content"] for m in sent)
        self.assertIn("build the thing", blob)

    def test_pause_with_no_active_task_is_noop(self):
        _, agent = self._agent()
        self.assertIsNone(agent.pause_task())


if __name__ == "__main__":
    unittest.main()
