"""Tests for the local↔cloud RAG comparison harness (jarvis.rag.compare)."""

import unittest

from jarvis.config.manager import ConfigManager
from jarvis.llm.gateway import LLMGateway
from jarvis.rag.compare import compare_providers, format_compare_report
from jarvis.rag.evaluation import ControlQuestion
from tests.fake_engine import FakeEngine


class FakeAgent:
    """Minimal agent exposing the two methods the harness calls."""

    def __init__(self, config, answers):
        self._config = config
        self._answers = answers          # question -> grounded_answer dict (or {"raise": True})
        self.calls = []                  # (provider, model, rag_rewrite) seen per grounded call

    def rag_retrieve(self, question, index_name, k):
        # One chunk from the expected source → retrieval hit.
        return ([{"metadata": {"filename": "kb.md"}, "text": "evidence text"}], [], None)

    def grounded_answer(self, question, index_name=None, k=None):
        rt = self._config.runtime
        self.calls.append((rt.get("provider"), rt.get("model"), rt.get("rag_rewrite")))
        spec = self._answers[question]
        if spec.get("raise"):
            raise RuntimeError("boom")
        return spec


def _grounded(text, filename="kb.md"):
    return {
        "text": text, "grounded": True, "idk": False,
        "results": [{"text": "evidence text", "metadata": {"filename": filename}}],
        "notice": None,
    }


def _questions():
    return [
        ControlQuestion(question="q1", expectation=["alpha"], expected_sources=["kb.md"]),
        ControlQuestion(question="q2", expectation=["beta"], expected_sources=["kb.md"]),
    ]


def _judge(verdict="YES"):
    return LLMGateway(FakeEngine(responder=lambda m, p: verdict))


class CompareTest(unittest.TestCase):
    def test_aggregates_and_columns(self):
        cfg = ConfigManager()
        answers = {"q1": _grounded("alpha is here, cites kb.md"),
                   "q2": _grounded("beta is here, cites kb.md")}
        agent = FakeAgent(cfg, answers)

        report = compare_providers(
            agent, cfg, _questions(), "kb",
            providers=[("ollama", "qwen2.5:7b"), ("openrouter", "cloud/model")],
            judge_gateway=_judge("YES"), judge_model="cloud/model",
            repeats=2, k=4,
        )

        self.assertEqual(report.retrieval_hit_rate, 1.0)
        self.assertEqual(len(report.providers), 2)
        local, cloud = report.providers
        self.assertEqual(local.provider, "ollama")
        self.assertEqual(cloud.provider, "openrouter")
        # 2 questions × 2 repeats.
        self.assertEqual(len(local.samples), 4)
        # Coverage/citation/judge all perfect given the crafted answers.
        self.assertEqual(local.coverage_mean, 1.0)
        self.assertEqual(local.citation_rate, 1.0)
        self.assertEqual(local.match_rate, 1.0)
        self.assertEqual(local.error_rate, 0.0)
        self.assertEqual(local.idk_rate, 0.0)
        # Report renders both columns.
        out = format_compare_report(report)
        self.assertIn("ollama/qwen2.5:7b", out)
        self.assertIn("openrouter/cloud/model", out)

    def test_forces_fair_retrieval_and_toggles_provider(self):
        cfg = ConfigManager()
        answers = {"q1": _grounded("alpha kb.md"), "q2": _grounded("beta kb.md")}
        agent = FakeAgent(cfg, answers)

        compare_providers(
            agent, cfg, _questions(), "kb",
            providers=[("ollama", "loc"), ("openrouter", "cl")],
            judge_gateway=_judge(), judge_model="cl", repeats=1, k=4,
        )
        # Each grounded call saw rag_rewrite off (parsed to bool False) and the
        # right provider/model.
        self.assertTrue(all(rw is False for _, _, rw in agent.calls))
        self.assertEqual(agent.calls[0][:2], ("ollama", "loc"))
        self.assertEqual(agent.calls[-1][:2], ("openrouter", "cl"))

    def test_restores_config_afterwards(self):
        cfg = ConfigManager()
        cfg.set("provider", "openrouter")
        cfg.set("rag_rewrite", "on")
        agent = FakeAgent(cfg, {"q1": _grounded("alpha kb.md"), "q2": _grounded("beta kb.md")})

        compare_providers(
            agent, cfg, _questions(), "kb",
            providers=[("ollama", "loc"), ("openrouter", "cl")],
            judge_gateway=_judge(), judge_model="cl", repeats=1, k=4,
        )
        # Snapshot/restore leaves the caller's settings exactly as they were.
        self.assertEqual(cfg.runtime.get("provider"), "openrouter")
        self.assertEqual(cfg.runtime.get("rag_rewrite"), True)

    def test_error_is_a_datapoint_not_a_crash(self):
        cfg = ConfigManager()
        answers = {"q1": {"raise": True}, "q2": _grounded("beta kb.md")}
        agent = FakeAgent(cfg, answers)

        report = compare_providers(
            agent, cfg, _questions(), "kb",
            providers=[("ollama", "loc")],
            judge_gateway=_judge(), judge_model="cl", repeats=1, k=4,
        )
        local = report.providers[0]
        self.assertEqual(local.error_rate, 0.5)   # 1 of 2 questions errored
        # Config still restored despite the error.
        self.assertNotIn("provider", cfg.runtime)

    def test_verdict_flip_detected(self):
        cfg = ConfigManager()
        agent = FakeAgent(cfg, {"q1": _grounded("alpha kb.md"), "q2": _grounded("beta kb.md")})
        # Judge flips YES/NO across calls → non-unanimous verdicts within a question.
        flip = [True, False, True, False]
        gw = LLMGateway(FakeEngine(responder=lambda m, p: "YES" if flip.pop(0) else "NO"))

        report = compare_providers(
            agent, cfg, _questions(), "kb",
            providers=[("ollama", "loc")],
            judge_gateway=gw, judge_model="cl", repeats=2, k=4,
        )
        self.assertGreater(report.providers[0].verdict_flip_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
