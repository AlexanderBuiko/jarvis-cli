"""Tests for the second-stage retrieval enhancements (filter, rerank, rewrite)."""

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
from jarvis.rag.enhance import (
    apply_filter,
    enhance_results,
    make_reranker,
    rewrite_query,
)
from tests.fake_engine import FakeEngine


def _r(cid, score, text="t", filename="f.md"):
    return {"text": text, "score": score,
            "metadata": {"chunk_id": cid, "filename": filename, "section": "S"}}


class FakeReranker:
    """Reverses the order so tests can detect that reranking ran."""
    def rerank(self, question, results):
        return [{**r, "rerank_score": float(i)} for i, r in enumerate(reversed(results))]


class FilterTest(unittest.TestCase):
    def test_threshold_and_top_n(self):
        results = [_r("a", 0.9), _r("b", 0.5), _r("c", 0.2), _r("d", 0.1)]
        kept = apply_filter(results, min_score=0.4)
        self.assertEqual([r["metadata"]["chunk_id"] for r in kept], ["a", "b"])
        kept = apply_filter(results, min_score=0.4, top_n=1)
        self.assertEqual([r["metadata"]["chunk_id"] for r in kept], ["a"])

    def test_never_empties_a_nonempty_input(self):
        results = [_r("a", 0.3), _r("b", 0.2)]
        kept = apply_filter(results, min_score=0.99)  # cutoff removes everything
        self.assertEqual([r["metadata"]["chunk_id"] for r in kept], ["a"])  # best retained


class EnhanceOrderTest(unittest.TestCase):
    def test_filter_then_rerank_then_top_n(self):
        results = [_r("a", 0.9), _r("b", 0.5), _r("c", 0.2)]
        out = enhance_results(results, min_score=0.4, top_n=1,
                              reranker=FakeReranker(), question="q")
        # 0.4 cutoff keeps [a, b]; FakeReranker reverses → [b, a]; top_n=1 → [b].
        self.assertEqual([r["metadata"]["chunk_id"] for r in out], ["b"])
        self.assertIn("rerank_score", out[0])

    def test_no_op_without_settings(self):
        results = [_r("a", 0.9), _r("b", 0.5)]
        self.assertEqual(enhance_results(results), results)


class RerankerFactoryTest(unittest.TestCase):
    def test_off_is_none(self):
        self.assertIsNone(make_reranker("off"))

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            make_reranker("bogus")

    def test_cross_encoder_without_package_raises_helpful(self):
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            with self.assertRaises(RuntimeError) as ctx:
                make_reranker("cross_encoder")
            self.assertIn("sentence-transformers", str(ctx.exception))
        else:
            self.skipTest("sentence-transformers is installed")


class RewriteQueryTest(unittest.TestCase):
    def test_returns_model_rewrite(self):
        gw = LLMGateway(FakeEngine(scripted=["cookie parameters FastAPI"]))
        out = rewrite_query(gw, "umm how do cookies work here", {})
        self.assertEqual(out, "cookie parameters FastAPI")

    def test_falls_back_to_original_when_blank(self):
        gw = LLMGateway(FakeEngine(scripted=["   "]))
        out = rewrite_query(gw, "original question", {})
        self.assertEqual(out, "original question")


class ConfigParamsTest(unittest.TestCase):
    def test_new_params_parse_and_validate(self):
        cfg = ConfigManager()
        cfg.set("rag_min_score", "0.3")
        cfg.set("rag_top_n", "3")
        cfg.set("rag_rerank", "cross_encoder")
        cfg.set("rag_rewrite", "on")
        rt = cfg.runtime
        self.assertEqual(rt["rag_min_score"], 0.3)
        self.assertEqual(rt["rag_top_n"], 3)
        self.assertEqual(rt["rag_rerank"], "cross_encoder")
        self.assertIs(rt["rag_rewrite"], True)

    def test_invalid_rerank_rejected(self):
        with self.assertRaises(ValueError):
            ConfigManager().set("rag_rerank", "magic")


class AgentEnhanceWiringTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name
        corpus = Path(self._tmp.name) / "kb"
        corpus.mkdir()
        for i in range(6):
            (corpus / f"doc{i}.md").write_text(
                f"# Doc {i}\n\nembeddings vector search chunk number {i}.\n", encoding="utf-8")
        IndexPipeline(FakeEmbedder(), IndexStore()).build(str(corpus), "kb", strategy="structure")

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def test_top_n_shrinks_enhanced_vs_raw(self):
        cfg = ConfigManager()
        cfg.set("rag_top_n", "2")
        agent = JarvisAgent(FakeEngine(scripted=["x"]), cfg)
        raw, enhanced, error = agent.rag_retrieve("embeddings vector search", "kb", 5)
        self.assertIsNone(error)
        self.assertEqual(len(raw), 5)
        self.assertEqual(len(enhanced), 2)

    def test_missing_reranker_package_degrades_without_crashing(self):
        try:
            import sentence_transformers  # noqa: F401
            self.skipTest("sentence-transformers is installed")
        except ImportError:
            pass
        cfg = ConfigManager()
        cfg.set("rag_rerank", "cross_encoder")
        agent = JarvisAgent(FakeEngine(scripted=["x"]), cfg)
        raw, enhanced, error = agent.rag_retrieve("embeddings vector search", "kb", 5)
        # No reranker available → falls back to cosine order, no exception.
        self.assertIsNone(error)
        self.assertEqual(len(enhanced), 5)


if __name__ == "__main__":
    unittest.main()
