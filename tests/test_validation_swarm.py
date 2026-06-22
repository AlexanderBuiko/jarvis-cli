"""
Tests for the validation swarm (jarvis/pipeline/swarm.py).

All model access is through a FakeEngine behind the LLMGateway — no network. The
tests cover: one reviewer's opinion parsing; the consolidator aggregating opinions
into each of the three decisions with the correct gate marker; the swarm runner
delegating non-validation stages to the base runner; an end-to-end validation turn
via Orchestrator.step producing the right gate verdict; a per-agent invariant flag;
and per-task accounting accumulation across the whole swarm.
"""

import tempfile
import unittest
from pathlib import Path

from jarvis.config.manager import ConfigManager
from jarvis.llm.gateway import LLMGateway
from jarvis.pipeline.base import MARKER_REPLAN, GATE_APPROVAL
from jarvis.pipeline.orchestrator import Orchestrator
from jarvis.pipeline.runner import LLMStageRunner
from jarvis.pipeline.stages import STAGE_AGENTS
from jarvis.pipeline.swarm import (
    DECISION_APPROVE,
    DECISION_REVISE_PLAN,
    DECISION_REWORK,
    ConsolidatorAgent,
    ReviewOpinion,
    SwarmStageRunner,
    default_reviewers,
)
from jarvis.session.task_store import TaskStore
from tests.fake_engine import FakeEngine


def _is_consolidator(messages) -> bool:
    return "consolidator" in messages[0]["content"].lower()


def _validation_task(store: TaskStore) -> dict:
    task = store.new_task("demo")
    task["stage"] = "validation"
    task["description"] = "Write a haiku about the sea"
    task["plan"] = "1. draft\n2. polish"
    task["stage_outputs"] = {"clarification": "must be 3 lines", "execution": "the sea is wide"}
    store.save(task)
    return task


class ReviewerParsingTest(unittest.TestCase):
    def test_parses_pass_issues_and_own_invariants(self):
        reviewer = default_reviewers()[2]  # Completeness (comp-1 / comp-2)
        raw = (
            "VERDICT: FAIL\n"
            "ISSUES:\n"
            "- step 2 is missing\n"
            "- output has a TODO\n"
            "INVARIANTS_VIOLATED:\n"
            "- comp-1: step has no output\n"
            "- not-mine: ignored\n"
        )
        op = reviewer.parse_opinion(raw)
        self.assertFalse(op.passed)
        self.assertEqual(op.issues, ["step 2 is missing", "output has a TODO"])
        # Only the reviewer's OWN invariant ids are kept; foreign ids are dropped.
        self.assertEqual(op.violated_invariants, ["comp-1"])

    def test_pass_with_no_issues(self):
        reviewer = default_reviewers()[0]
        op = reviewer.parse_opinion("VERDICT: PASS\nISSUES:\n- none\nINVARIANTS_VIOLATED:\n- none")
        self.assertTrue(op.passed)
        self.assertEqual(op.issues, [])
        self.assertEqual(op.violated_invariants, [])


class ConsolidatorTest(unittest.TestCase):
    def setUp(self):
        self.cons = ConsolidatorAgent()
        self.opinions = [
            ReviewOpinion("Correctness", passed=True),
            ReviewOpinion("Completeness", passed=False, issues=["x"], violated_invariants=["comp-1"]),
        ]

    def _review(self, decision_text):
        decision, rationale = self.cons.parse_decision(decision_text)
        return self.cons.build_review(decision, rationale, self.opinions)

    def test_approve_has_no_marker(self):
        review = self._review("DECISION: APPROVE\nRATIONALE: looks good")
        self.assertEqual(review.decision, DECISION_APPROVE)
        self.assertNotIn(MARKER_REPLAN, review.text)

    def test_rework_has_no_marker(self):
        review = self._review("DECISION: REWORK_EXECUTION\nRATIONALE: fix the output")
        self.assertEqual(review.decision, DECISION_REWORK)
        self.assertNotIn(MARKER_REPLAN, review.text)

    def test_revise_plan_carries_replan_marker(self):
        review = self._review("DECISION: REVISE_PLAN\nRATIONALE: the plan is wrong")
        self.assertEqual(review.decision, DECISION_REVISE_PLAN)
        self.assertIn(MARKER_REPLAN, review.text)

    def test_unparseable_defaults_to_rework_not_approve(self):
        review = self._review("I think it's mostly fine maybe")
        self.assertEqual(review.decision, DECISION_REWORK)
        self.assertNotIn(MARKER_REPLAN, review.text)

    def test_breakdown_surfaces_flagged_own_invariant(self):
        review = self._review("DECISION: REWORK_EXECUTION\nRATIONALE: r")
        self.assertIn("comp-1", review.text)  # the per-agent invariant flag is visible


class _RecordingRunner:
    """A base StageRunner stand-in that records it was delegated to."""

    def __init__(self):
        self.calls = []

    def run(self, task, entry_message, extra_system=""):
        self.calls.append((task["stage"], entry_message))
        return "base-runner-output"


class SwarmRunnerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tasks = TaskStore(Path(self._tmp.name))
        self.config = ConfigManager()

    def tearDown(self):
        self._tmp.cleanup()

    def _runner(self, engine, base=None):
        return SwarmStageRunner(
            LLMGateway(engine), self.config, base or _RecordingRunner(), self.tasks
        )

    def test_delegates_non_validation_stage_to_base(self):
        self.config.set("review_agents", "5")
        base = _RecordingRunner()
        runner = self._runner(FakeEngine(), base)
        task = self.tasks.new_task("demo")  # clarification
        out = runner.run(task, "entry")
        self.assertEqual(out, "base-runner-output")
        self.assertEqual(base.calls, [("clarification", "entry")])

    def test_swarm_off_delegates_validation_to_base(self):
        # review_agents defaults to 1 -> the single validator (base runner).
        base = _RecordingRunner()
        runner = self._runner(FakeEngine(), base)
        task = _validation_task(self.tasks)
        out = runner.run(task, "validate")
        self.assertEqual(out, "base-runner-output")
        self.assertEqual(base.calls, [("validation", "validate")])

    def test_swarm_on_runs_panel_and_consolidates(self):
        self.config.update(["model=test/m", "review_agents=3"])

        def responder(messages, params):
            if _is_consolidator(messages):
                return "DECISION: REVISE_PLAN\nRATIONALE: the plan misses a step"
            return "VERDICT: FAIL\nISSUES:\n- bad\nINVARIANTS_VIOLATED:\n- none"

        engine = FakeEngine(responder=responder)
        runner = self._runner(engine)
        task = _validation_task(self.tasks)
        out = runner.run(task, "validate")
        # 3 reviewers + 1 consolidator.
        self.assertEqual(len(engine.calls), 4)
        self.assertIn(MARKER_REPLAN, out)
        # The consolidated turn is persisted on the task transcript.
        self.assertEqual(task["messages"][-1]["content"], out)

    def test_accounting_accumulates_every_swarm_call(self):
        self.config.update(["model=test/m", "review_agents=4"])

        def responder(messages, params):
            if _is_consolidator(messages):
                return "DECISION: APPROVE\nRATIONALE: ok"
            return "VERDICT: PASS\nISSUES:\n- none\nINVARIANTS_VIOLATED:\n- none"

        engine = FakeEngine(responder=responder)
        runner = self._runner(engine)
        task = _validation_task(self.tasks)
        runner.run(task, "validate")
        # 4 reviewers + 1 consolidator = 5 calls; FakeEngine reports 2 tokens each.
        self.assertEqual(task["api_call_count"], 5)
        self.assertEqual(task["total_tokens"], 10)

    def test_concurrent_panel_accounting_is_deterministic(self):
        # Reviewers always run concurrently; accounting still merges in panel order.
        self.config.update(["model=test/m", "review_agents=5"])

        def responder(messages, params):
            if _is_consolidator(messages):
                return "DECISION: APPROVE\nRATIONALE: ok"
            return "VERDICT: PASS\nISSUES:\n- none\nINVARIANTS_VIOLATED:\n- none"

        runner = self._runner(FakeEngine(responder=responder))
        task = _validation_task(self.tasks)
        runner.run(task, "validate")
        self.assertEqual(task["api_call_count"], 6)  # 5 reviewers + consolidator


class SwarmEndToEndTest(unittest.TestCase):
    """Drive the swarm through Orchestrator.step and check the gate verdict."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tasks = TaskStore(Path(self._tmp.name))
        self.config = ConfigManager()
        self.config.update(["model=test/m", "review_agents=5"])

    def tearDown(self):
        self._tmp.cleanup()

    def _orchestrator(self, consolidator_decision):
        def responder(messages, params):
            if _is_consolidator(messages):
                return f"DECISION: {consolidator_decision}\nRATIONALE: synthesized"
            return "VERDICT: FAIL\nISSUES:\n- issue\nINVARIANTS_VIOLATED:\n- none"

        gateway = LLMGateway(FakeEngine(responder=responder))
        base = LLMStageRunner(
            gateway, self.config, _NullMemory(), _NullStore(), _NullStore(),
            _NullChecker(), self.tasks,
        )
        runner = SwarmStageRunner(gateway, self.config, base, self.tasks)
        return Orchestrator(STAGE_AGENTS, self.tasks, runner)

    def test_revise_plan_recommends_replan_at_gate(self):
        orch = self._orchestrator(DECISION_REVISE_PLAN)
        task = _validation_task(self.tasks)
        result = orch.step(task)
        self.assertEqual(result.verdict.gate, GATE_APPROVAL)
        # The 3-way gate is intact, and the swarm's REVISE_PLAN annotated it.
        self.assertTrue(result.verdict.replan_recommended)
        self.assertEqual(result.verdict.confirm_target, "done")
        self.assertEqual(result.verdict.reject_target, "execution")
        self.assertEqual(result.verdict.replan_target, "planning")
        self.assertEqual(task["stage"], "validation")  # no auto-advance at the gate

    def test_approve_does_not_recommend_replan(self):
        orch = self._orchestrator(DECISION_APPROVE)
        task = _validation_task(self.tasks)
        result = orch.step(task)
        self.assertEqual(result.verdict.gate, GATE_APPROVAL)
        self.assertFalse(result.verdict.replan_recommended)


# ── Minimal collaborators so the base LLMStageRunner runs without real services ──


class _NullMemory:
    def build_task_context(self, history):
        return []


class _NullStore:
    def read_active(self):
        return ""


class _NullChecker:
    def validate(self, *a, **k):  # never called: no invariants configured
        raise AssertionError("invariant checker should not run with no invariants")


if __name__ == "__main__":
    unittest.main()
