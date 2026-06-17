"""
Integration tests for the mentor's two required behaviours:

  * pausing at any phase (state is preserved),
  * resuming without repeated explanations (a fresh thread still knows the plan).

These drive the real JarvisAgent against a FakeEngine, with $HOME pointed at a
temp dir so all of ~/.jarvis (threads, tasks, sessions, memory) is isolated.
"""

import os
import tempfile
import unittest

from jarvis.agent import JarvisAgent
from jarvis.config.manager import ConfigManager
from tests.fake_engine import FakeEngine


def _pipeline_responder(messages, params):
    """Answer stage entry messages with marker-tagged text; plain text otherwise."""
    last = messages[-1]["content"]
    if "enough to write a plan" in last:        # clarifier entry
        return "Understood the task.\n[[READY]]"
    if "Produce the concrete" in last:          # planner entry
        return "THE PLAN: step 1, step 2.\n[[READY]]"
    if "executing the approved plan" in last:   # executor entry
        return "Starting; I need your input.\n[[NEEDS_USER]]"
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

    def test_pause_at_any_phase_preserves_state(self):
        # Drive the pipeline to a gate at execution (plan recorded), then pause.
        engine, agent = self._agent(_pipeline_responder)
        agent.create_task("demo")
        agent.run_task()

        self.assertEqual(agent.active_task["stage"], "execution")
        self.assertIn("THE PLAN", agent.active_task["plan"])

        paused = agent.pause_task()
        self.assertEqual(paused, "demo")
        self.assertIsNone(agent.active_task)

        # The task file still holds the stage and plan after pausing.
        task = agent._tasks.find("demo")
        self.assertEqual(task["stage"], "execution")
        self.assertIn("THE PLAN", task["plan"])

    def test_resume_in_new_thread_without_re_explaining(self):
        engine, agent = self._agent(_pipeline_responder)
        agent.create_task("demo")
        agent.run_task()  # -> execution gate, plan recorded
        agent.pause_task()

        # Brand-new, empty thread: no conversation history to lean on.
        agent.new_thread("fresh")
        self.assertEqual(agent.history, [])
        self.assertTrue(agent.start_task("demo"))

        engine.responder = lambda m, p: "We are mid-execution."
        agent.chat("Where are we?")

        # The plan reached the model via the working-memory block, not history —
        # the user never re-explained it in this thread.
        sent = engine.calls[-1][0]
        blob = "\n".join(m["content"] for m in sent)
        self.assertIn("THE PLAN", blob)
        # And it was not because the user typed it.
        user_said = [m["content"] for m in sent if m["role"] == "user"]
        self.assertFalse(any("THE PLAN" in u and "Where are we" in u for u in user_said))

    def test_pause_with_no_active_task_is_noop(self):
        engine, agent = self._agent()
        self.assertIsNone(agent.pause_task())


if __name__ == "__main__":
    unittest.main()
