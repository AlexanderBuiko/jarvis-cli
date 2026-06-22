"""
Tests for the components extracted from JarvisAgent during the KB-alignment
refactor: the LLM gateway, the memory coordinator (incl. the bounded task
context bugfix), the conversation service, the personalization service, and an
end-to-end smoke test that the agent still wires together with a fake engine.
"""

import os
import tempfile
import unittest
from pathlib import Path

from jarvis.config.manager import ConfigManager
from jarvis.llm.gateway import LLMGateway
from jarvis.memory.coordinator import MemoryCoordinator, DEFAULT_WINDOW_SIZE
from jarvis.conversation.service import ConversationService
from jarvis.personalization.service import PersonalizationService
from jarvis.session.thread_store import ThreadStore
from jarvis.session.profile_store import ProfileStore
from jarvis.session.behavior_log import BehaviorLog
from tests.fake_engine import FakeEngine


class LLMGatewayTest(unittest.TestCase):
    def test_complete_appends_accounting_record(self):
        gw = LLMGateway(FakeEngine(scripted=["hello"]))
        calls: list[dict] = []
        completion = gw.complete([{"role": "user", "content": "hi"}], {}, label="final_answer", api_calls=calls)
        self.assertEqual(completion.text, "hello")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["label"], "final_answer")
        self.assertEqual(calls[0]["index"], 1)

    def test_complete_without_api_calls_does_not_record(self):
        gw = LLMGateway(FakeEngine(scripted=["x"]))
        completion = gw.complete([{"role": "user", "content": "hi"}], {})
        self.assertEqual(completion.text, "x")

    def test_record_mints_explicit_index(self):
        gw = LLMGateway(FakeEngine(scripted=["x"]))
        completion = gw.complete([{"role": "user", "content": "hi"}], {})
        rec = gw.record(0, "context_compression", completion)
        self.assertEqual(rec["index"], 0)
        self.assertEqual(rec["label"], "context_compression")


class MemoryCoordinatorTaskContextTest(unittest.TestCase):
    """The high-severity bugfix: task transcripts are bounded, not unbounded."""

    def _coord(self, **cfg):
        config = ConfigManager()
        for k, v in cfg.items():
            config.set(k, str(v))
        return MemoryCoordinator(LLMGateway(FakeEngine()), config)

    def _transcript(self, turns):
        msgs = []
        for i in range(turns):
            msgs.append({"role": "user", "content": f"u{i}"})
            msgs.append({"role": "assistant", "content": f"a{i}"})
        return msgs

    def test_long_task_transcript_is_windowed_to_default(self):
        coord = self._coord()
        msgs = self._transcript(50)  # 100 messages
        out = coord.build_task_context(msgs)
        self.assertEqual(len(out), DEFAULT_WINDOW_SIZE * 2)
        self.assertEqual(out[-1], {"role": "assistant", "content": "a49"})

    def test_window_size_config_bounds_task_context(self):
        coord = self._coord(window_size=3)
        out = coord.build_task_context(self._transcript(20))
        self.assertEqual(len(out), 6)

    def test_short_transcript_returned_whole(self):
        coord = self._coord()
        msgs = self._transcript(2)
        self.assertEqual(coord.build_task_context(msgs), msgs)


class ConversationServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ThreadStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_starts_with_a_fresh_thread(self):
        svc = ConversationService(self.store)
        self.assertEqual(svc.state.history, [])
        self.assertTrue(svc.state.id)

    def test_new_load_rename_delete_lifecycle(self):
        svc = ConversationService(self.store)
        first_id = svc.state.id
        svc.state.history.append({"role": "user", "content": "hi"})
        svc.save()

        svc.new_thread("second")
        self.assertEqual(svc.state.name, "second")
        self.assertNotEqual(svc.state.id, first_id)

        self.assertEqual(svc.rename_thread("renamed"), "renamed")
        self.assertEqual(svc.state.name, "renamed")

        self.assertTrue(svc.load_thread(first_id))
        self.assertEqual(svc.state.history, [{"role": "user", "content": "hi"}])

        msg = svc.delete_thread("renamed")
        self.assertIn("deleted", msg)

    def test_reset_clears_active_thread(self):
        svc = ConversationService(self.store)
        svc.state.history.append({"role": "user", "content": "hi"})
        svc.state.total_tokens = 99
        svc.save()
        svc.reset()
        self.assertEqual(svc.state.history, [])
        self.assertEqual(svc.state.total_tokens, 0)


class PersonalizationServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.profile = ProfileStore(d)
        self.behavior = BehaviorLog(d / "behavior.jsonl")

    def tearDown(self):
        self._tmp.cleanup()

    def _svc(self, scripted=None):
        gw = LLMGateway(FakeEngine(scripted=scripted or []))
        return PersonalizationService(gw, ConfigManager(), self.profile, self.behavior)

    def test_onboarding_writes_profile(self):
        svc = self._svc()
        self.assertFalse(svc.exists())
        svc.onboard("brief answers", "kotlin only", "android dev")
        self.assertTrue(svc.exists())
        self.assertIn("brief answers", svc.read())

    def test_nudge_fires_every_n_interactions(self):
        svc = self._svc()
        svc.onboard("brief", "x", "y")  # a Style section now exists
        for _ in range(4):
            svc.record_interaction(
                user_input="hi", response_chars=10,
                solution_strategy="direct", context_strategy="none", had_task=False,
            )
        self.assertIsNone(svc.maybe_nudge())  # 4 interactions: no nudge
        svc.record_interaction(
            user_input="hi", response_chars=10,
            solution_strategy="direct", context_strategy="none", had_task=False,
        )
        self.assertIsNotNone(svc.maybe_nudge())  # 5th: nudge

    def test_propose_style_requires_a_profile(self):
        svc = self._svc()
        current, proposed, error = svc.propose_style()
        self.assertIsNotNone(error)


class StageRunnerAccountingTest(unittest.TestCase):
    """Task pipeline turns now accumulate their LLM spend onto the task."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_stage_turn_accounts_requests_and_tokens(self):
        from jarvis.pipeline.runner import LLMStageRunner
        from jarvis.pipeline.invariants import InvariantChecker
        from jarvis.session.task_store import TaskStore
        from jarvis.session.profile_store import ProfileStore
        from jarvis.session.invariant_store import InvariantStore

        gw = LLMGateway(FakeEngine(scripted=["did the step"]))
        config = ConfigManager()
        tasks = TaskStore(self._dir / "tasks")
        runner = LLMStageRunner(
            gw, config, MemoryCoordinator(gw, config),
            ProfileStore(self._dir), InvariantStore(self._dir),
            InvariantChecker(gw), tasks,
        )
        task = tasks.new_task("demo")
        task["stage"] = "execution"
        task["plan"] = "1. a"
        task["plan_steps"] = ["a"]

        runner.run(task, "Work on step 1", "")
        # One stage_turn call (no invariants configured), 2 tokens from the fake usage.
        self.assertEqual(task["api_call_count"], 1)
        self.assertEqual(task["total_tokens"], 2)
        # Persisted to disk.
        self.assertEqual(tasks.load(task["id"])["api_call_count"], 1)


class AttachmentTest(unittest.TestCase):
    """Finished task results can be pinned to a thread and enrich chat context."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ThreadStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_attach_detach_and_persist(self):
        svc = ConversationService(self.store)
        svc.attach("id1", "research", "found 42", "# Findings\n42")
        self.assertEqual(len(svc.attachments()), 1)
        # Persisted and reloaded by a fresh service over the same store.
        reloaded = ConversationService(self.store)
        self.assertTrue(any(a["name"] == "research" for a in reloaded.attachments()))
        # Detach removes it.
        self.assertEqual(svc.detach("research"), "research")
        self.assertEqual(svc.attachments(), [])

    def test_attach_replaces_same_task(self):
        svc = ConversationService(self.store)
        svc.attach("id1", "research", "v1", "first")
        svc.attach("id1", "research", "v2", "second")
        self.assertEqual(len(svc.attachments()), 1)
        self.assertEqual(svc.attachments()[0]["content"], "second")

    def test_attachments_block_injects_content(self):
        from jarvis.prompt_builder.builder import build_attachments_block
        block = build_attachments_block([
            {"task_id": "1", "name": "research", "summary": "s", "content": "the answer is 42"},
        ])
        self.assertEqual(len(block), 2)
        self.assertIn("the answer is 42", block[0]["content"])
        self.assertIn("research", block[0]["content"])
        self.assertEqual(build_attachments_block([]), [])


class AgentAttachmentFlowTest(unittest.TestCase):
    """End-to-end: a finished task attaches to its thread and shows up in chat."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name

    def tearDown(self):
        if self._old_home is not None:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def test_finish_active_task_attaches_and_exits(self):
        from jarvis.agent import JarvisAgent
        agent = JarvisAgent(FakeEngine(scripted=["x"]), ConfigManager())
        agent.create_task("t2")
        name = agent.finish_active_task("a summary", "the deliverable")
        self.assertEqual(name, "t2")
        self.assertIsNone(agent.active_task)  # task was exited
        self.assertTrue(any(a["name"] == "t2" for a in agent.list_attachments()))

    def test_attached_result_enters_chat_context(self):
        from jarvis.agent import JarvisAgent
        engine = FakeEngine(scripted=["ok"])
        agent = JarvisAgent(engine, ConfigManager())
        agent.create_task("research")
        agent.save_task_result("# Findings\nThe answer is 42.")
        self.assertEqual(agent.attach_task("research"), "research")
        agent.exit_task()
        agent.chat("what did we find?")
        sent = " ".join(m["content"] for m in engine.calls[-1][0])
        self.assertIn("The answer is 42.", sent)

    def test_delete_task_detaches_from_active_thread(self):
        from jarvis.agent import JarvisAgent
        engine = FakeEngine(scripted=["ok", "ok"])
        agent = JarvisAgent(engine, ConfigManager())
        agent.create_task("research")
        agent.save_task_result("# Findings\nThe answer is 42.")
        agent.attach_task("research")
        agent.exit_task()
        self.assertTrue(agent.list_attachments())

        self.assertEqual(agent.delete_task("research"), "research")
        # The attachment is gone, so the deliverable no longer enters chat context.
        self.assertEqual(agent.list_attachments(), [])
        agent.chat("what did we find?")
        sent = " ".join(m["content"] for m in engine.calls[-1][0])
        self.assertNotIn("The answer is 42.", sent)

    def test_delete_task_detaches_from_other_threads(self):
        from jarvis.agent import JarvisAgent
        agent = JarvisAgent(FakeEngine(scripted=["ok"]), ConfigManager())
        agent.create_task("research")
        agent.save_task_result("# Findings\nThe answer is 42.")
        agent.attach_task("research")   # pinned on the current thread
        agent.exit_task()
        original = agent.thread_name
        # Move to a different thread, then delete the task from there.
        agent.new_thread("other")
        self.assertEqual(agent.list_attachments(), [])  # the new thread has none
        agent.delete_task("research")
        # The original thread's on-disk attachment must also be purged.
        self.assertTrue(agent.load_thread(original))
        self.assertEqual(agent.list_attachments(), [])


class AgentEndToEndSmokeTest(unittest.TestCase):
    """The whole composition root still works end-to-end with a fake engine."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name

    def tearDown(self):
        if self._old_home is not None:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def test_chat_turn_records_history_and_persists(self):
        from jarvis.agent import JarvisAgent
        engine = FakeEngine(scripted=["Hello there."])
        agent = JarvisAgent(engine, ConfigManager())
        reply = agent.chat("hi")
        self.assertIn("Hello there.", reply)
        self.assertEqual(len(agent.history), 2)
        # Persisted to the thread store under the isolated HOME.
        threads = list((Path(self._tmp.name) / ".jarvis" / "threads").glob("*.json"))
        self.assertTrue(threads)


if __name__ == "__main__":
    unittest.main()
