"""Tests for the unattended execution loop (jarvis/pipeline/loop.py).

The loop drives tasks through the pipeline with no human at the gates, so the
tests script a FakeDriver that returns a deterministic sequence of StageResults
and assert the loop's gate policy, its outcome classification, and the metrics.
No LLM, no network, no git — the driver and committer are fakes.
"""

import unittest

from jarvis.pipeline.base import GATE_APPROVAL, GATE_QUESTION, StageVerdict
from jarvis.pipeline.orchestrator import StageResult
from jarvis.pipeline.loop import (
    ExecutionLoop,
    LoopReport,
    NullCommitter,
    OUTCOME_DONE,
    OUTCOME_FAILED,
    OUTCOME_HUNG,
    OUTCOME_STUCK,
    TaskMetric,
    TaskSpec,
    parse_pool,
)


# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeDriver:
    """A scripted stand-in for JarvisAgent's task surface.

    Constructed with a list of (StageResult, post_stage) turns. Each pipeline_step
    returns the next turn's result and (like the real orchestrator's forward
    advance) sets the stage to post_stage. When the script runs out it returns a
    harmless continue_stage so the loop runs to its turn cap.
    """

    def __init__(self, turns):
        self._turns = list(turns)
        self._task = None
        self.saved = None
        self.finished = None

    @property
    def active_task(self):
        return dict(self._task) if self._task else None

    def create_task(self, name=None):
        self._task = {"name": name, "stage": "clarification",
                      "api_call_count": 0, "total_cost": 0.0}
        return dict(self._task)

    def pipeline_step(self, extra_instruction=""):
        if self._task is None:
            return None
        self._task["api_call_count"] += 1
        self._task["total_cost"] += 0.01
        if not self._turns:
            return StageResult(stage=self._task["stage"],
                               verdict=StageVerdict(continue_stage=True))
        result, post = self._turns.pop(0)
        if post is not None:
            self._task["stage"] = post
        return result

    def advance_to(self, target):
        if self._task is not None:
            self._task["stage"] = target
        return target

    def save_task_result(self, text):
        self.saved = text

    def finish_active_task(self, summary, deliverable):
        self.finished = (summary, deliverable)
        self._task = None
        return "task"


class RecordingCommitter:
    def __init__(self):
        self.messages = []

    def commit(self, message):
        self.messages.append(message)
        return f"sha{len(self.messages)}"


# ── Turn factories (readability) ────────────────────────────────────────────


def _ready(stage, post):
    return (StageResult(stage=stage, verdict=StageVerdict(ready=True), advanced_to=post), post)


def _continue(stage):
    return (StageResult(stage=stage, verdict=StageVerdict(continue_stage=True)), None)


def _plan_gate():
    return (StageResult(stage="planning", verdict=StageVerdict(
        gate=GATE_APPROVAL, confirm_target="execution", reject_target="planning")), None)


def _validate(confirm=True, fail=False, replan=False):
    return (StageResult(stage="validation", verdict=StageVerdict(
        gate=GATE_APPROVAL, confirm_target="done", reject_target="execution",
        replan_target="planning", fail_recommended=fail, replan_recommended=replan)), None)


def _question(stage="clarification"):
    return (StageResult(stage=stage, verdict=StageVerdict(gate=GATE_QUESTION)), None)


def _done_turn():
    # Reached only after the validation gate confirmed -> advance_to('done').
    return (StageResult(stage="done", text="SUMMARY: shipped it\n\nthe deliverable"), None)


_HAPPY = [
    _ready("clarification", "planning"),
    _plan_gate(),
    _continue("execution"),
    _ready("execution", "validation"),
    _validate(confirm=True),
    _done_turn(),
]


def _run(turns, **kw):
    driver = FakeDriver(turns)
    committer = RecordingCommitter()
    loop = ExecutionLoop(driver, committer, provider="test", **kw)
    report = loop.run([TaskSpec(name="t", request="do it", kind="feature")])
    return driver, committer, report.metrics[0]


# ── Outcome classification ──────────────────────────────────────────────────


class OutcomeTest(unittest.TestCase):
    def test_happy_path_reaches_done_first_pass(self):
        driver, committer, m = _run(list(_HAPPY))
        self.assertEqual(m.outcome, OUTCOME_DONE)
        self.assertEqual(m.stage_reached, "done")
        self.assertTrue(m.first_pass)
        self.assertEqual(m.reworks, 0)
        self.assertEqual(driver.finished[0], "shipped it")   # SUMMARY: stripped
        self.assertEqual(driver.saved, "SUMMARY: shipped it\n\nthe deliverable")

    def test_one_commit_per_task_records_outcome(self):
        _, committer, _ = _run(list(_HAPPY))
        self.assertEqual(len(committer.messages), 1)
        self.assertIn("done", committer.messages[0])

    def test_rework_then_pass_is_done_but_not_first_pass(self):
        turns = [
            _ready("clarification", "planning"), _plan_gate(),
            _ready("execution", "validation"), _validate(fail=True),
            _ready("execution", "validation"), _validate(confirm=True),
            _done_turn(),
        ]
        _, _, m = _run(turns)
        self.assertEqual(m.outcome, OUTCOME_DONE)
        self.assertFalse(m.first_pass)
        self.assertEqual(m.reworks, 1)

    def test_persistent_validation_failure_is_failed(self):
        turns = [
            _ready("clarification", "planning"), _plan_gate(),
            _ready("execution", "validation"), _validate(fail=True),
            _ready("execution", "validation"), _validate(fail=True),
            _ready("execution", "validation"), _validate(fail=True),
        ]
        _, _, m = _run(turns, max_reworks=1)
        self.assertEqual(m.outcome, OUTCOME_FAILED)
        self.assertIn("non-working", m.break_reason)

    def test_replan_recommended_routes_back_to_planning(self):
        driver = FakeDriver([
            _ready("clarification", "planning"), _plan_gate(),
            _ready("execution", "validation"), _validate(replan=True, fail=True),
            _ready("execution", "validation"), _validate(confirm=True), _done_turn(),
        ])
        loop = ExecutionLoop(driver, NullCommitter(), provider="test")
        report = loop.run([TaskSpec("t", "do it")])
        self.assertEqual(report.metrics[0].outcome, OUTCOME_DONE)
        self.assertEqual(report.metrics[0].reworks, 1)

    def test_endless_clarification_is_stuck(self):
        turns = [_question(), _question(), _question(), _question()]
        _, _, m = _run(turns, max_questions=2)
        self.assertEqual(m.outcome, OUTCOME_STUCK)
        self.assertIn("clarification", m.break_reason)

    def test_turn_cap_is_hung(self):
        _, _, m = _run([_continue("execution")], max_turns=4)
        self.assertEqual(m.outcome, OUTCOME_HUNG)
        self.assertEqual(m.turns, 4)


# ── Report metrics ──────────────────────────────────────────────────────────


class ReportTest(unittest.TestCase):
    def _metric(self, name, outcome, first_pass=False, seconds=10.0):
        return TaskMetric(name=name, kind="feature", outcome=outcome,
                          stage_reached="done" if outcome == OUTCOME_DONE else "execution",
                          wall_seconds=seconds, turns=5, first_pass=first_pass)

    def test_streak_stops_at_first_break(self):
        r = LoopReport(provider="test", metrics=[
            self._metric("a", OUTCOME_DONE, True),
            self._metric("b", OUTCOME_DONE, True),
            self._metric("c", OUTCOME_FAILED),
            self._metric("d", OUTCOME_DONE, True),
        ])
        self.assertEqual(r.streak, 2)
        self.assertEqual(r.completed, 3)
        self.assertEqual(r.broke_on.name, "c")

    def test_first_pass_rate_and_avg(self):
        r = LoopReport(provider="test", metrics=[
            self._metric("a", OUTCOME_DONE, True, seconds=10.0),
            self._metric("b", OUTCOME_DONE, False, seconds=20.0),
        ])
        self.assertEqual(r.first_pass_rate, 0.5)
        self.assertEqual(r.avg_seconds, 15.0)

    def test_all_done_has_no_break(self):
        r = LoopReport(provider="x", metrics=[self._metric("a", OUTCOME_DONE, True)])
        self.assertIsNone(r.broke_on)
        self.assertIn("nothing", r.to_markdown())

    def test_markdown_and_jsonl_render(self):
        r = LoopReport(provider="cloud", metrics=[self._metric("a", OUTCOME_DONE, True)])
        md = r.to_markdown()
        self.assertIn("Execution loop — cloud", md)
        self.assertIn("| # | task |", md)
        jsonl = r.to_jsonl()
        self.assertIn('"provider": "cloud"', jsonl)
        self.assertEqual(len(jsonl.strip().splitlines()), 2)  # header + one task


# ── Pool parser ─────────────────────────────────────────────────────────────


class PoolParserTest(unittest.TestCase):
    def test_parses_kinds_bullets_and_numbers(self):
        specs = parse_pool(
            "# Task pool\n\n"
            "- [bug] add() is wrong for negatives; fix it.\n"
            "* [refactor] split the god module.\n"
            "1. [tests] cover the parser.\n"
            "2) plain feature with no tag.\n"
            "just prose, ignored\n"
        )
        self.assertEqual([s.kind for s in specs], ["bug", "refactor", "test", "feature"])
        self.assertEqual(specs[0].name, "add() is wrong for negatives")
        self.assertEqual(specs[2].kind, "test")   # 'tests' normalised to 'test'

    def test_unknown_tag_is_kept_in_request_not_treated_as_kind(self):
        specs = parse_pool("- [urgent] do the thing.")
        self.assertEqual(specs[0].kind, "feature")
        self.assertIn("[urgent]", specs[0].request)

    def test_empty_pool(self):
        self.assertEqual(parse_pool("# just a heading\n\nsome prose"), [])


if __name__ == "__main__":
    unittest.main()
