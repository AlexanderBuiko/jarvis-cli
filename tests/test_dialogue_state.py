"""Tests for the dialogue_state "task memory" strategy and the mini-chat scenario.

The integration test is the mentor's check: two long (12-message) RAG dialogues,
asserting the assistant (a) never loses the goal — the task-state block with the
goal is present on the final turn — and (b) keeps answering with Sources.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.agent import JarvisAgent
from jarvis.config.manager import ConfigManager
from jarvis.indexing.embeddings import FakeEmbedder
from jarvis.indexing.pipeline import IndexPipeline
from jarvis.indexing.store import IndexStore
from jarvis.llm.gateway import LLMGateway
from jarvis.memory.coordinator import MemoryCoordinator
from tests.fake_engine import FakeEngine


class DialogueStateStrategyTest(unittest.TestCase):
    def _coord(self, engine):
        cfg = ConfigManager()
        cfg.set("context_strategy", "dialogue_state")
        return MemoryCoordinator(LLMGateway(engine), cfg)

    def test_context_prepends_state_block_and_keeps_history(self):
        coord = self._coord(FakeEngine())
        history = [{"role": "user", "content": "hi"},
                   {"role": "assistant", "content": "yo"}]
        ctx = coord.build_chat_context(history, facts="Goal: X\nGiven: a\nConstraints: b")
        self.assertIn("Task state", ctx[0]["content"])
        self.assertIn("Goal: X", ctx[0]["content"])
        self.assertEqual(ctx[-1]["content"], "yo")  # full history preserved after block

    def test_no_state_returns_plain_history(self):
        coord = self._coord(FakeEngine())
        ctx = coord.build_chat_context([{"role": "user", "content": "hi"}], facts=None)
        self.assertEqual([m["content"] for m in ctx], ["hi"])

    def test_run_background_updates_state(self):
        engine = FakeEngine(scripted=["Goal: Y\nGiven: none yet\nConstraints: none yet"])
        coord = self._coord(engine)
        res = coord.run_background(
            history=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
            active_topic=None, summary=None, summary_covered_turns=0,
            facts=None, topic_summaries={},
        )
        self.assertIn("Goal: Y", res.facts)
        self.assertIsNotNone(res.record)


GOALS = {
    "auth": "set up JWT authentication in FastAPI",
    "trip": "plan a two-week trip to Japan",
}

SCENARIOS = {
    "auth": [
        "I want to secure my FastAPI app.", "Use OAuth2 with password flow.",
        "How do I hash passwords?", "Tokens should expire in 30 minutes.",
        "How do I return a 401 on bad credentials?", "Add a /users/me endpoint.",
        "How do I validate the token on each request?", "Keep it Python 3.12.",
        "How do I test the login flow?", "Add CORS for my frontend.",
        "How do I handle refresh tokens?", "Summarize what we've set up.",
    ],
    "trip": [
        "Help me plan a trip to Japan.", "Two weeks in spring.",
        "I want Tokyo and Kyoto.", "Budget is moderate.",
        "How do I get between cities?", "I love food and temples.",
        "Avoid very touristy spots.", "Vegetarian options matter.",
        "How many days in Kyoto?", "Add a day trip idea.",
        "Keep walking distances short.", "Recap the plan so far.",
    ],
}


class MiniChatScenarioTest(unittest.TestCase):
    """Two long RAG dialogues with task memory: goal retained + sources every turn."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name
        corpus = Path(self._tmp.name) / "kb"
        corpus.mkdir()
        for name in ("auth", "web", "food"):
            (corpus / f"{name}.md").write_text(
                f"# {name}\n\nGuidance about {name}: tokens, endpoints, and options.\n",
                encoding="utf-8")
        IndexPipeline(FakeEmbedder(), IndexStore()).build(str(corpus), "kb", strategy="structure")

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def test_scenario_auth(self):
        self._assert_scenario("auth")

    def test_scenario_trip(self):
        self._assert_scenario("trip")

    def _assert_scenario(self, key):
        goal = GOALS[key]
        engine_holder = {}

        def responder(messages, params):
            engine_holder["last"] = messages
            blob = "\n".join((m.get("content") or "") for m in messages)
            if "Update the task state" in blob:
                return (f"Goal: {goal}\nGiven: details gathered so far\n"
                        "Constraints: fixed terms so far")
            if "Knowledge base — excerpts" in blob:
                return "Here's how, based on the docs [1]."
            return "ok"

        engine = FakeEngine(responder=responder)
        cfg = ConfigManager()
        cfg.set("context_strategy", "dialogue_state")
        cfg.set("rag", "on")
        cfg.set("rag_index", "kb")
        cfg.set("rag_cite", "on")   # debug view: assert Sources persist across turns
        agent = JarvisAgent(engine, cfg)

        replies = [agent.chat(msg) for msg in SCENARIOS[key]]
        self.assertEqual(len(replies), 12)
        for i, reply in enumerate(replies, 1):
            self.assertIn("Sources:", reply, f"turn {i} lost its sources")

        # Goal retained in task state to the end.
        self.assertIn(goal, agent.facts)

        # Goal injected into the final answer's prompt (task memory in context).
        final_answer_calls = [
            msgs for msgs, _ in engine.calls
            if any("Knowledge base — excerpts" in (m.get("content") or "") for m in msgs)
        ]
        last_prompt = "\n".join((m.get("content") or "") for m in final_answer_calls[-1])
        self.assertIn("[Task state", last_prompt)
        self.assertIn(goal, last_prompt)


if __name__ == "__main__":
    unittest.main()
