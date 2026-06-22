"""
Integration tests for standalone task workspaces (decoupled from threads).

A task carries its own conversation; entering/leaving it never touches chat
threads. $HOME is a temp dir so all of ~/.jarvis is isolated per test. The
pipeline is driven via agent.pipeline_step() + agent.advance_to().
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


class StandaloneTaskTest(unittest.TestCase):
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
        agent.pipeline_step()                         # clarification READY -> planning
        r = agent.pipeline_step()                     # planning -> approval gate
        self.assertEqual(r.verdict.gate, GATE_APPROVAL)
        agent.advance_to(r.verdict.confirm_target)    # Confirm -> execution
        agent.pipeline_step()                         # execution step 1 -> STEP_DONE

    def test_task_is_not_linked_to_a_thread(self):
        _, agent = self._agent(_responder)
        task = agent.create_task("demo")
        # Entering a task does not touch the thread's active-task linkage (gone).
        self.assertEqual(agent.active_task["id"], task["id"])
        # Thread files carry no task reference any more.
        import json, pathlib
        for f in (pathlib.Path(self._tmp.name) / ".jarvis" / "threads").glob("*.json"):
            self.assertNotIn("active_task_id", json.loads(f.read_text()))

    def test_exit_returns_to_chat_and_preserves_task(self):
        _, agent = self._agent(_responder)
        agent.create_task("demo")
        self._drive_into_execution(agent)
        self.assertEqual(agent.active_task["stage"], "execution")

        self.assertEqual(agent.exit_task(), "demo")
        self.assertIsNone(agent.active_task)  # back in chat mode

        # The task persists on disk with its progress.
        task = agent._tasks.find("demo")
        self.assertEqual(task["stage"], "execution")
        self.assertEqual(task["step_index"], 1)
        self.assertIn("build the thing", task["plan"])

    def test_task_has_its_own_conversation_not_the_thread(self):
        engine, agent = self._agent(_responder)
        agent.create_task("demo")
        self._drive_into_execution(agent)

        # The task accumulated its own transcript; the chat thread stayed empty.
        self.assertTrue(len(agent.active_task["messages"]) > 0)
        self.assertEqual(agent.history, [])

    def test_resume_continues_from_saved_step(self):
        engine, agent = self._agent(_responder)
        agent.create_task("demo")
        self._drive_into_execution(agent)   # step_index now 1
        agent.exit_task()

        # Re-enter the task later (no thread involved) and it resumes from step 2.
        self.assertTrue(agent.start_task("demo"))
        from jarvis.pipeline.stages import ExecutorAgent
        entry = ExecutorAgent().entry_message(agent.active_task)
        self.assertIn("step 2 of 2", entry)

    def test_exit_with_no_task_is_noop(self):
        _, agent = self._agent()
        self.assertIsNone(agent.exit_task())

    def test_illegal_transition_is_handled_gracefully(self):
        # An attempt to skip a stage (e.g. clarification -> done) must not crash the
        # REPL: advance_to surfaces it as a clean None and the FSM stays put. (In
        # normal flow the target always comes from a verdict, so this is defensive.)
        _, agent = self._agent(_responder)
        agent.create_task("demo")  # clarification
        self.assertIsNone(agent.advance_to("done"))
        self.assertEqual(agent.active_task["stage"], "clarification")


if __name__ == "__main__":
    unittest.main()
