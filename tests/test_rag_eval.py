"""Tests for the RAG A/B comparison and control-question evaluation."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.agent import JarvisAgent
from jarvis.config.manager import ConfigManager
from jarvis.indexing.embeddings import FakeEmbedder
from jarvis.indexing.pipeline import IndexPipeline
from jarvis.indexing.store import IndexStore
from jarvis.rag import (
    ControlQuestion,
    evaluate,
    format_report,
    load_questions,
    DEFAULT_QUESTIONS_PATH,
)
from tests.fake_engine import FakeEngine

ERRORS_DOC = "# Errors\n\nUse HTTPException with status_code 404 and raise it.\n"
STATIC_DOC = "# Static\n\nServe assets with StaticFiles and mount them.\n"


def _grounded_or_dunno(messages, params):
    """Grounded answers echo the injected context (keywords + citations); the
    un-grounded answer is a generic miss. Lets scoring tell the modes apart."""
    blob = "\n".join((m.get("content") or "") for m in messages)
    if "Knowledge base — excerpts" in blob:
        return blob
    return "I don't have specific information about that."


QUESTIONS = [
    ControlQuestion("how to return a 404 error with HTTPException",
                    ["HTTPException", "404"], ["errors.md"]),
    ControlQuestion("how to serve static files",
                    ["StaticFiles", "mount"], ["static.md"]),
]


class EvalHarnessTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name
        corpus = Path(self._tmp.name) / "kb"
        corpus.mkdir()
        (corpus / "errors.md").write_text(ERRORS_DOC, encoding="utf-8")
        (corpus / "static.md").write_text(STATIC_DOC, encoding="utf-8")
        IndexPipeline(FakeEmbedder(), IndexStore()).build(str(corpus), "kb", strategy="structure")

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def _agent(self):
        return JarvisAgent(FakeEngine(responder=_grounded_or_dunno), ConfigManager())

    def test_compare_rag_returns_distinct_answers(self):
        plain, grounded, results, error = self._agent().compare_rag(
            "how to return a 404 error with HTTPException", "kb", 3)
        self.assertIsNone(error)
        self.assertNotIn("Knowledge base", plain)        # plain is un-grounded
        self.assertIn("HTTPException", grounded)          # grounded saw the chunk
        self.assertTrue(results)

    def test_full_eval_scores_retrieval_and_quality(self):
        report = evaluate(self._agent(), QUESTIONS, "kb", k=3, generate_answers=True)
        self.assertEqual(report.n, 2)
        self.assertEqual(report.retrieval_hit_rate, 1.0)   # expected source in top-k
        self.assertEqual(report.avg_plain_coverage, 0.0)   # generic answer misses keywords
        self.assertEqual(report.avg_rag_coverage, 1.0)     # grounded answer has them
        self.assertEqual(report.citation_rate, 1.0)        # cites errors.md / static.md
        self.assertEqual(report.improved, 2)

    def test_retrieval_only_eval_makes_no_chat_calls(self):
        engine = FakeEngine(responder=_grounded_or_dunno)
        agent = JarvisAgent(engine, ConfigManager())
        report = evaluate(agent, QUESTIONS, "kb", k=3, generate_answers=False)
        self.assertEqual(engine.calls, [])                 # no answers generated
        self.assertEqual(report.retrieval_hit_rate, 1.0)
        self.assertIsNone(report.results[0].rag_answer)

    def test_eval_records_error_for_missing_index(self):
        report = evaluate(self._agent(), QUESTIONS, "nope", k=3, generate_answers=False)
        self.assertFalse(report.results[0].retrieval_hit)
        self.assertIsNotNone(report.results[0].error)

    def test_format_report_renders_summary(self):
        report = evaluate(self._agent(), QUESTIONS, "kb", k=3, generate_answers=True)
        text = format_report(report)
        self.assertIn("Summary", text)
        self.assertIn("Retrieval hit-rate", text)
        self.assertIn("with RAG", text)


class ShippedQuestionsTest(unittest.TestCase):
    def test_default_questions_file_is_valid(self):
        questions = load_questions(DEFAULT_QUESTIONS_PATH)
        self.assertEqual(len(questions), 10)
        for q in questions:
            self.assertTrue(q.question)
            self.assertTrue(q.expectation)
            self.assertTrue(q.expected_sources)

    def test_expected_sources_exist_in_corpus(self):
        repo_root = Path(__file__).resolve().parent.parent
        kb = repo_root / "knowledge_base"
        for q in load_questions(DEFAULT_QUESTIONS_PATH):
            for src in q.expected_sources:
                self.assertTrue((kb / src).exists(), f"missing corpus file: {src}")


if __name__ == "__main__":
    unittest.main()
