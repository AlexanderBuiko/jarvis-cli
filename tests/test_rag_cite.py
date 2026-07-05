"""Tests for mandatory citations and the weak-context 'I don't know' gate."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.agent import JarvisAgent
from jarvis.config.manager import ConfigManager
from jarvis.indexing.embeddings import FakeEmbedder
from jarvis.indexing.pipeline import IndexPipeline
from jarvis.indexing.store import IndexStore
from jarvis.rag.cite import (
    build_citations,
    cited_indices,
    idk_message,
    pick_quote,
    strip_trailing_citations,
)
from jarvis.rag import evaluate, ControlQuestion
from tests.fake_engine import FakeEngine

CHUNK_TEXT = "To return a 404 error you raise HTTPException with status_code 404. It stops the request."


def _res(cid, text=CHUNK_TEXT, filename="handling-errors.md", section="Errors", score=0.6):
    return {"text": text, "score": score,
            "metadata": {"chunk_id": cid, "filename": filename, "section": section}}


class CiteUnitTest(unittest.TestCase):
    def test_cited_indices_parses_markers_in_range(self):
        self.assertEqual(cited_indices("uses [1] and [3] here", 3), [1, 3])
        self.assertEqual(cited_indices("out of range [9]", 3), [])
        self.assertEqual(cited_indices("no markers", 3), [])

    def test_cited_indices_parses_multi_number_brackets(self):
        # The model often groups citations as "[3, 1]" or "[1,2,3]".
        self.assertEqual(cited_indices("see [3, 1] and [2]", 5), [3, 1, 2])
        self.assertEqual(cited_indices("all [1,2,3]", 5), [1, 2, 3])
        self.assertEqual(cited_indices("mixed [2, 9]", 5), [2])  # 9 out of range dropped

    def test_pick_quote_is_verbatim_substring(self):
        quote = pick_quote(CHUNK_TEXT, "how to return a 404 error")
        self.assertIn(quote.rstrip("…"), CHUNK_TEXT)
        self.assertIn("404", quote)

    def test_build_citations_has_sources_and_quotes(self):
        block = build_citations([_res("a:0"), _res("b:1", filename="other.md")],
                                "answer with no markers", "how to 404")
        self.assertIn("Sources:", block)
        self.assertIn("Quotes:", block)
        self.assertIn("handling-errors.md › Errors  (a:0)", block)
        self.assertIn("other.md", block)  # both cited when no [n] markers

    def test_build_citations_honours_markers(self):
        block = build_citations([_res("a:0"), _res("b:1", filename="other.md")],
                                "I used [1] only", "q")
        self.assertIn("a:0", block)
        self.assertNotIn("other.md", block)  # [1] → only the first chunk

    def test_quote_numbers_match_inline_citations(self):
        results = [_res("a:0", filename="a.md"), _res("b:1", filename="b.md"),
                   _res("c:2", filename="c.md")]
        # Model cites [3] and [1] (not [1],[2]); quotes must keep those numbers.
        block = build_citations(results, "import [3] then instance [1].", "q")
        self.assertIn("[3] c.md", block)
        self.assertIn("[1] a.md", block)
        self.assertNotIn("[2]", block)  # excerpt 2 was never cited

    def test_empty_results_no_block(self):
        self.assertEqual(build_citations([], "x", "q"), "")

    def test_strip_model_generated_sources(self):
        answer = ("Use gt=0 [1] for the path param [2].\n\n"
                  "Sources:\n  [1] path-params.md: says gt means greater than\n"
                  "  [2] path-params.md: floats")
        clean = strip_trailing_citations(answer)
        self.assertEqual(clean, "Use gt=0 [1] for the path param [2].")
        self.assertNotIn("Sources:", clean)

    def test_strip_keeps_answer_without_citation_block(self):
        answer = "Just a plain answer with an inline [1] marker."
        self.assertEqual(strip_trailing_citations(answer), answer)

    def test_idk_message_declines_and_asks(self):
        msg = idk_message("q", 0.12, 0.4)
        self.assertIn("I don't know", msg)
        self.assertIn("clarify", msg.lower())


class JudgeTest(unittest.TestCase):
    def _gw(self, reply):
        from jarvis.llm.gateway import LLMGateway
        return LLMGateway(FakeEngine(scripted=[reply]))

    def test_yes_and_no_parse(self):
        from jarvis.rag.judge import judge_supported
        self.assertTrue(judge_supported(self._gw("YES, clearly supported."), "a", "q"))
        self.assertFalse(judge_supported(self._gw("NO — unsupported"), "a", "q"))

    def test_empty_inputs_are_false_without_calling(self):
        from jarvis.rag.judge import judge_supported
        engine_reply = self._gw("YES")
        self.assertFalse(judge_supported(engine_reply, "", "q"))
        self.assertFalse(judge_supported(engine_reply, "a", ""))


class ConfigTest(unittest.TestCase):
    def test_new_params(self):
        cfg = ConfigManager()
        cfg.set("rag_cite", "off")
        cfg.set("rag_strict", "on")
        cfg.set("rag_idk_threshold", "0.4")
        rt = cfg.runtime
        self.assertIs(rt["rag_cite"], False)
        self.assertIs(rt["rag_strict"], True)
        self.assertEqual(rt["rag_idk_threshold"], 0.4)

    def test_idk_threshold_range(self):
        with self.assertRaises(ValueError):
            ConfigManager().set("rag_idk_threshold", "2")


class AgentGroundedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name
        corpus = Path(self._tmp.name) / "kb"
        corpus.mkdir()
        (corpus / "handling-errors.md").write_text(
            f"# Errors\n\n{CHUNK_TEXT}\n", encoding="utf-8")
        IndexPipeline(FakeEmbedder(), IndexStore()).build(str(corpus), "kb", strategy="structure")

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def _agent(self, engine, **cfg):
        c = ConfigManager()
        c.set("rag_index", "kb")
        for k, v in cfg.items():
            c.set(k, v)
        return JarvisAgent(engine, c)

    def test_strong_context_appends_sources_and_quotes(self):
        agent = self._agent(FakeEngine(scripted=["Here is the answer."]))
        g = agent.grounded_answer("how do I return a 404 error", "kb", 5)
        self.assertTrue(g["grounded"])
        self.assertFalse(g["idk"])
        self.assertIn("Sources:", g["text"])
        self.assertIn("Quotes:", g["text"])
        self.assertIn("handling-errors.md", g["text"])

    def test_model_self_sources_are_deduplicated(self):
        # The model wrongly writes its own Sources block; only ours should remain.
        model_answer = "Use gt=0 [1].\n\nSources:\n  [1] path-params.md: greater than"
        agent = self._agent(FakeEngine(scripted=[model_answer]))
        g = agent.grounded_answer("how do I require item_id > 0", "kb", 5)
        self.assertEqual(g["text"].count("Sources:"), 1)
        self.assertTrue(g["text"].startswith("Use gt=0 [1]."))
        self.assertIn("Quotes:", g["text"])

    def test_strict_weak_context_says_idk(self):
        agent = self._agent(FakeEngine(scripted=["should not be used"]),
                            rag_strict="on", rag_idk_threshold="0.99")
        g = agent.grounded_answer("something only vaguely related", "kb", 5)
        self.assertTrue(g["idk"])
        self.assertIn("I don't know", g["text"])
        self.assertNotIn("Sources:", g["text"])

    def test_augmented_weak_context_answers_normally(self):
        # Same weak context, but strict OFF → normal answer, no refusal, no sources.
        agent = self._agent(FakeEngine(scripted=["a normal answer"]),
                            rag_idk_threshold="0.99")
        g = agent.grounded_answer("something only vaguely related", "kb", 5)
        self.assertFalse(g["idk"])
        self.assertFalse(g["grounded"])
        self.assertEqual(g["text"], "a normal answer")

    def test_chat_strict_weak_skips_model(self):
        engine = FakeEngine(scripted=["must not be called"])
        agent = self._agent(engine, rag="on", rag_strict="on", rag_idk_threshold="0.99")
        reply = agent.chat("unrelated question")
        self.assertIn("I don't know", reply)
        self.assertEqual(engine.calls, [])  # deterministic gate, no LLM call

    def test_chat_strong_appends_citations(self):
        engine = FakeEngine(scripted=["The answer is to raise HTTPException."])
        agent = self._agent(engine, rag="on")
        reply = agent.chat("how do I return a 404 error")
        self.assertIn("Sources:", reply)
        self.assertIn("Quotes:", reply)
        self.assertTrue(engine.calls)


class EvalChecksTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name
        corpus = Path(self._tmp.name) / "kb"
        corpus.mkdir()
        (corpus / "errors.md").write_text(f"# Errors\n\n{CHUNK_TEXT}\n", encoding="utf-8")
        IndexPipeline(FakeEmbedder(), IndexStore()).build(str(corpus), "kb", strategy="structure")

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def test_eval_reports_sources_quotes_and_match(self):
        # Fake model: grounded answer for the RAG turn; "YES" for the judge call.
        def responder(messages, params):
            blob = "\n".join((m.get("content") or "") for m in messages)
            if "supported by the sources" in blob:         # the LLM judge
                return "YES"
            if "Knowledge base — excerpts" in blob:        # the grounded answer
                return "You raise HTTPException with status_code 404 to return the error."
            return "generic"
        agent = JarvisAgent(FakeEngine(responder=responder), ConfigManager())
        qs = [ControlQuestion("how to return a 404 error with HTTPException",
                              ["HTTPException", "404"], ["errors.md"])]
        report = evaluate(agent, qs, "kb", k=5, generate_answers=True)
        r = report.results[0]
        self.assertTrue(r.has_sources)
        self.assertTrue(r.has_quotes)
        self.assertTrue(r.quote_match)
        self.assertEqual(report.sources_rate, 1.0)
        self.assertEqual(report.quotes_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
