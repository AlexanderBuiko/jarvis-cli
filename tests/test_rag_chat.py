"""Tests for RAG chat mode: config flags, the rag block, and agent wiring."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.agent import JarvisAgent
from jarvis.config.manager import ConfigManager
from jarvis.indexing.embeddings import FakeEmbedder
from jarvis.indexing.pipeline import IndexPipeline
from jarvis.indexing.store import IndexStore
from jarvis.prompt_builder.builder import build_rag_block
from tests.fake_engine import FakeEngine

DISTINCTIVE = "Pasta must be boiled in salted water until al dente."


class RagConfigTest(unittest.TestCase):
    def test_rag_flags_parse_and_validate(self):
        cfg = ConfigManager()
        cfg.set("rag", "on")
        cfg.set("rag_index", "kb")
        cfg.set("rag_k", "3")
        rt = cfg.runtime
        self.assertEqual(rt["rag"], True)
        self.assertEqual(rt["rag_index"], "kb")
        self.assertEqual(rt["rag_k"], 3)

    def test_rag_k_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            ConfigManager().set("rag_k", "0")


class RagBlockTest(unittest.TestCase):
    def test_empty_results_no_block(self):
        self.assertEqual(build_rag_block([]), [])

    def test_block_carries_text_and_citation(self):
        results = [{
            "score": 0.9, "text": "Boil the pasta.",
            "metadata": {"filename": "pasta.md", "section": "Cooking > Pasta"},
        }]
        block = build_rag_block(results)
        joined = "\n".join(m["content"] for m in block)
        self.assertIn("Boil the pasta.", joined)
        self.assertIn("pasta.md › Cooking > Pasta", joined)


class RagAgentTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name
        # Build an index under the isolated HOME (~/.jarvis/indexes) with the
        # offline fake embedder; the header records provider 'fake', so the
        # agent's retrieval rebuilds the same embedder from that header.
        corpus = Path(self._tmp.name) / "kb"
        corpus.mkdir()
        (corpus / "pasta.md").write_text(f"# Pasta\n\n{DISTINCTIVE}\n", encoding="utf-8")
        IndexPipeline(FakeEmbedder(), IndexStore()).build(str(corpus), "kb", strategy="structure")

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def _messages_sent(self, engine: FakeEngine) -> str:
        return "\n".join(
            m.get("content") or ""
            for call_messages, _ in engine.calls
            for m in call_messages
        )

    def test_rag_off_does_not_inject_chunks(self):
        engine = FakeEngine(scripted=["generic answer"])
        agent = JarvisAgent(engine, ConfigManager())
        reply = agent.chat("how do I cook pasta?")
        self.assertEqual(reply, "generic answer")
        self.assertNotIn(DISTINCTIVE, self._messages_sent(engine))

    def test_rag_on_injects_chunks_and_notice(self):
        engine = FakeEngine(scripted=["grounded answer"])
        cfg = ConfigManager()
        cfg.set("rag", "on")
        cfg.set("rag_index", "kb")
        agent = JarvisAgent(engine, cfg)
        reply = agent.chat("how do I cook pasta?")
        # The retrieved chunk text reached the model …
        self.assertIn(DISTINCTIVE, self._messages_sent(engine))
        # … and the user sees a grounding notice naming the source.
        self.assertIn("RAG: grounded", reply)
        self.assertIn("pasta.md", reply)

    def test_rag_on_missing_index_answers_with_notice(self):
        engine = FakeEngine(scripted=["still answers"])
        cfg = ConfigManager()
        cfg.set("rag", "on")
        cfg.set("rag_index", "does-not-exist")
        agent = JarvisAgent(engine, cfg)
        reply = agent.chat("anything")
        self.assertIn("still answers", reply)
        self.assertIn("not found", reply)
        self.assertNotIn(DISTINCTIVE, self._messages_sent(engine))

    def test_rag_on_without_index_name_notifies(self):
        engine = FakeEngine(scripted=["answer"])
        cfg = ConfigManager()
        cfg.set("rag", "on")  # rag_index deliberately unset
        agent = JarvisAgent(engine, cfg)
        reply = agent.chat("anything")
        self.assertIn("no rag_index is set", reply)


if __name__ == "__main__":
    unittest.main()
