"""
Execution loop — drive a whole POOL of tasks through the pipeline unattended.

The interactive driver (``jarvis/repl/loop.py``) pauses at every gate: a
free-text question, a plan-approval, the final done decision. That is right for a
human at the keyboard, but it makes an autonomous "take a task → run → commit →
take the next" loop impossible. This module is the headless counterpart: it drives
each task to ``done`` while resolving gates by policy (auto-confirm, auto-answer,
bounded rework), commits after every task, and records one ``TaskMetric`` per task
so the run can be measured — how many finished in a row, where it broke and why,
average time, and the first-pass rate.

It depends only on a small ``TaskDriver`` protocol (which ``JarvisAgent``
satisfies structurally) and a ``Committer`` protocol, so the pipeline layer never
imports the REPL and the whole thing is testable with fakes.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from .base import GATE_APPROVAL, GATE_QUESTION
from .orchestrator import StageResult

# ── Contracts ─────────────────────────────────────────────────────────────────


@runtime_checkable
class TaskDriver(Protocol):
    """The slice of ``JarvisAgent`` the loop needs — satisfied structurally.

    Kept to the public task surface so the pipeline layer never reaches into the
    agent's internals and a ``FakeDriver`` can stand in for tests.
    """

    @property
    def active_task(self) -> dict | None: ...

    def create_task(self, name: str | None = None) -> dict: ...

    def pipeline_step(self, extra_instruction: str = "") -> StageResult | None: ...

    def advance_to(self, target: str) -> str | None: ...

    def save_task_result(self, text: str): ...

    def finish_active_task(self, summary: str, deliverable: str) -> str | None: ...


@runtime_checkable
class Committer(Protocol):
    """Commits the working tree after a task. Returns a short report line."""

    def commit(self, message: str) -> str: ...


class GitCommitter:
    """Commits the sandbox repo after each task, one commit per task.

    Uses ``--allow-empty`` so the git log mirrors the execution log exactly even
    when a task produced no file change (e.g. a research task) — a task that ran
    is always a commit. Never raises: a commit failure degrades to a report
    string so one bad task cannot abort the whole loop.
    """

    def __init__(self, repo: Path | str) -> None:
        self._repo = Path(repo)

    def commit(self, message: str) -> str:
        try:
            subprocess.run(
                ["git", "-C", str(self._repo), "add", "-A"],
                capture_output=True, text=True, check=True,
            )
            subprocess.run(
                ["git", "-C", str(self._repo), "commit", "--allow-empty", "-m", message],
                capture_output=True, text=True, check=True,
            )
            sha = subprocess.run(
                ["git", "-C", str(self._repo), "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, check=True,
            )
            return sha.stdout.strip()
        except (subprocess.CalledProcessError, OSError) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            return f"commit failed: {detail.strip()}"


class NullCommitter:
    """No-op committer for dry runs and tests."""

    def commit(self, message: str) -> str:  # noqa: D401 — trivial
        return ""


# ── Data carriers ───────────────────────────────────────────────────────────


@dataclass
class TaskSpec:
    """One task from the pool."""
    name: str          # short title (used for the task workspace and git message)
    request: str       # the full instruction handed to the pipeline
    kind: str = "feature"  # declared type tag: bug/feature/refactor/test/docs/research


# Terminal outcomes for one task. Anything other than DONE breaks the streak.
OUTCOME_DONE = "done"        # reached the done stage — the deliverable was produced
OUTCOME_STUCK = "stuck"      # kept asking to clarify — did not understand from context
OUTCOME_FAILED = "failed"    # validation kept failing after rework — non-working result
OUTCOME_HUNG = "hung"        # hit the turn cap without a verdict — hung / looping
OUTCOME_BLOCKED = "blocked"  # a stage input contract was not satisfied

_BREAK_REASON = {
    OUTCOME_STUCK: "kept asking for clarification — did not understand the task from context",
    OUTCOME_FAILED: "validation kept failing after rework — likely a non-working result",
    OUTCOME_HUNG: "reached the turn cap without finishing — hung or looping",
    OUTCOME_BLOCKED: "a stage precondition was not satisfied",
}


@dataclass
class TaskMetric:
    """The measured outcome of running one task."""
    name: str
    kind: str
    outcome: str
    stage_reached: str
    wall_seconds: float
    turns: int                   # pipeline_step calls spent on this task
    api_calls: int = 0           # provider requests (from the task's own accounting)
    cost: float = 0.0            # accumulated $ cost (0.0 for local models)
    reworks: int = 0             # rework/replan cycles the validator triggered
    first_pass: bool = False     # reached done with zero reworks
    break_reason: str = ""       # why it broke (empty when done)
    commit: str = ""             # the committer's report line (sha or error)

    def as_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "outcome": self.outcome,
            "stage_reached": self.stage_reached, "wall_seconds": round(self.wall_seconds, 2),
            "turns": self.turns, "api_calls": self.api_calls, "cost": round(self.cost, 6),
            "reworks": self.reworks, "first_pass": self.first_pass,
            "break_reason": self.break_reason, "commit": self.commit,
        }


@dataclass
class LoopReport:
    """The whole run: per-task metrics plus the headline numbers the KB asks for."""
    provider: str
    metrics: list[TaskMetric] = field(default_factory=list)

    @property
    def streak(self) -> int:
        """Tasks finished in a row from the start before the first break."""
        n = 0
        for m in self.metrics:
            if m.outcome != OUTCOME_DONE:
                break
            n += 1
        return n

    @property
    def completed(self) -> int:
        return sum(1 for m in self.metrics if m.outcome == OUTCOME_DONE)

    @property
    def first_pass_rate(self) -> float:
        """Share of ALL tasks that reached done with no rework."""
        if not self.metrics:
            return 0.0
        return sum(1 for m in self.metrics if m.first_pass) / len(self.metrics)

    @property
    def avg_seconds(self) -> float:
        if not self.metrics:
            return 0.0
        return sum(m.wall_seconds for m in self.metrics) / len(self.metrics)

    @property
    def broke_on(self) -> TaskMetric | None:
        """The first task that did not finish, or None if all finished."""
        return next((m for m in self.metrics if m.outcome != OUTCOME_DONE), None)

    def to_jsonl(self) -> str:
        head = {"provider": self.provider, "streak": self.streak,
                "completed": self.completed, "total": len(self.metrics)}
        lines = [json.dumps(head)]
        lines += [json.dumps(m.as_dict()) for m in self.metrics]
        return "\n".join(lines) + "\n"

    def to_markdown(self) -> str:
        total = len(self.metrics)
        broke = self.broke_on
        lines = [
            f"# Execution loop — {self.provider}",
            "",
            f"- **Completed in a row (streak):** {self.streak} / {total}",
            f"- **Completed total:** {self.completed} / {total}",
            f"- **First-pass rate:** {self.first_pass_rate * 100:.0f}%",
            f"- **Average time/task:** {self.avg_seconds:.1f}s",
        ]
        if broke:
            lines.append(f"- **Broke on:** '{broke.name}' ({broke.outcome}) — {broke.break_reason}")
        else:
            lines.append("- **Broke on:** nothing — the whole pool finished.")
        lines += [
            "",
            "| # | task | kind | outcome | stage | time | reqs | $ | rework | 1st | commit |",
            "|---|------|------|---------|-------|------|------|---|--------|-----|--------|",
        ]
        for i, m in enumerate(self.metrics, 1):
            lines.append(
                f"| {i} | {m.name} | {m.kind} | {m.outcome} | {m.stage_reached} | "
                f"{m.wall_seconds:.0f}s | {m.api_calls} | {m.cost:.4f} | {m.reworks} | "
                f"{'✓' if m.first_pass else '·'} | `{m.commit}` |"
            )
        return "\n".join(lines) + "\n"


# ── The pool parser ─────────────────────────────────────────────────────────

# A pool line: a markdown list item ("- ", "* ", "1. ", "1) "), optionally
# prefixed with a "[kind]" tag. Headings, blanks and prose are ignored.
_POOL_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)\s*$")
_KIND_TAG = re.compile(r"^\[(?P<kind>[a-zA-Z]+)\]\s*(?P<rest>.*)$")
_KNOWN_KINDS = {"bug", "feature", "refactor", "test", "tests", "docs", "doc", "research"}


def parse_pool(text: str) -> list[TaskSpec]:
    """Parse a tracker file into an ordered list of ``TaskSpec``.

    The format is deliberately "even a text file": one markdown list item per
    task, an optional leading ``[kind]`` tag, the rest is the instruction. The
    task name is a short slug of the instruction (first sentence, capped) so the
    git log and metric table stay readable.
    """
    specs: list[TaskSpec] = []
    for line in text.splitlines():
        m = _POOL_ITEM.match(line)
        if not m:
            continue
        body = m.group(1).strip()
        kind = "feature"
        tag = _KIND_TAG.match(body)
        if tag and tag.group("kind").lower() in _KNOWN_KINDS:
            kind = tag.group("kind").lower().rstrip("s") or "feature"
            if kind == "doc":
                kind = "docs"
            body = tag.group("rest").strip()
        if not body:
            continue
        specs.append(TaskSpec(name=_slug(body), request=body, kind=kind))
    return specs


def _slug(text: str, limit: int = 60) -> str:
    """A short, readable task name: the first sentence, capped at ``limit``."""
    first = re.split(r"(?<=[.;:])\s", text, maxsplit=1)[0].strip().rstrip(".;:, ")
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


# ── The loop ────────────────────────────────────────────────────────────────


class ExecutionLoop:
    """Drive a pool of tasks through the pipeline unattended, committing each.

    The gate policy is the whole point: a human would decide at each gate, so an
    unattended run needs a rule.
      - approval gate  → confirm and finish, UNLESS the validator flagged a failure
        ([[FAIL]]/[[REPLAN]]), in which case rework (bounded by ``max_reworks``);
      - question gate  → answer "proceed with sensible defaults" (bounded by
        ``max_questions`` — past the bound the task is declared STUCK, i.e. the
        model could not work it out from context);
      - turn cap       → declare the task HUNG.
    ``max_reworks`` bounds how many times a failing validation is retried before
    the task is declared FAILED (non-working result).
    """

    def __init__(
        self,
        driver: TaskDriver,
        committer: Committer,
        provider: str = "unknown",
        *,
        max_turns: int = 60,
        max_reworks: int = 2,
        max_questions: int = 2,
        clock: Callable[[], float] = time.monotonic,
        on_event: Callable[[str, TaskMetric], None] | None = None,
    ) -> None:
        self._driver = driver
        self._committer = committer
        self._provider = provider
        self._max_turns = max_turns
        self._max_reworks = max_reworks
        self._max_questions = max_questions
        self._clock = clock
        self._on_event = on_event

    def run(self, specs: list[TaskSpec]) -> LoopReport:
        report = LoopReport(provider=self._provider)
        for spec in specs:
            if self._on_event:
                self._on_event("task_start", TaskMetric(
                    name=spec.name, kind=spec.kind, outcome="", stage_reached="",
                    wall_seconds=0.0, turns=0,
                ))
            metric = self._run_one(spec)
            metric.commit = self._committer.commit(f"[{metric.outcome}] {spec.name}")
            report.metrics.append(metric)
            if self._on_event:
                self._on_event("task_done", metric)
        return report

    def _run_one(self, spec: TaskSpec) -> TaskMetric:
        start = self._clock()
        self._driver.create_task(spec.name)
        pending = (
            f"The user says: {spec.request}\n\n"
            f"(Task type: {spec.kind}. Work fully autonomously to a finished deliverable.)"
        )
        turns = reworks = questions = 0
        api_calls = 0
        cost = 0.0
        stage_reached = "clarification"
        outcome = OUTCOME_HUNG

        while turns < self._max_turns:
            turns += 1
            if self._driver.active_task is None:
                outcome = OUTCOME_BLOCKED
                break

            result = self._driver.pipeline_step(pending)
            pending = ""
            if result is None:
                outcome = OUTCOME_BLOCKED
                break
            if result.blocked:
                outcome = OUTCOME_BLOCKED
                stage_reached = result.stage
                break

            task = self._driver.active_task
            if task is not None:
                stage_reached = task["stage"]
                api_calls = task.get("api_call_count", api_calls)
                cost = task.get("total_cost", cost)

            # Reached the terminal stage: the deliverable is this turn's output.
            if task is not None and task["stage"] == "done":
                deliverable = result.text
                summary = _first_line(deliverable) or spec.name
                self._driver.save_task_result(deliverable)
                self._driver.finish_active_task(summary, deliverable)
                outcome = OUTCOME_DONE
                stage_reached = "done"
                break

            verdict = result.verdict
            if verdict is None:
                continue  # in-stage progress with no gate — keep driving

            if verdict.gate == GATE_APPROVAL:
                if verdict.replan_recommended or verdict.fail_recommended:
                    reworks += 1
                    if reworks > self._max_reworks:
                        outcome = OUTCOME_FAILED
                        break
                    target, pending = self._rework(verdict)
                    self._driver.advance_to(target)
                else:
                    self._driver.advance_to(verdict.confirm_target or "done")
                continue

            if verdict.gate == GATE_QUESTION:
                questions += 1
                if questions > self._max_questions:
                    outcome = OUTCOME_STUCK
                    break
                pending = (
                    "Proceed autonomously: use sensible defaults and your best judgment. "
                    "Do not ask further questions — later stages cannot ask the user."
                )
                continue
            # continue_stage / forward advance handled by the orchestrator — loop on.

        wall = self._clock() - start
        return TaskMetric(
            name=spec.name, kind=spec.kind, outcome=outcome,
            stage_reached=stage_reached, wall_seconds=wall, turns=turns,
            api_calls=api_calls, cost=cost, reworks=reworks,
            first_pass=(outcome == OUTCOME_DONE and reworks == 0),
            break_reason=("" if outcome == OUTCOME_DONE else _BREAK_REASON.get(outcome, "")),
        )

    def _rework(self, verdict) -> tuple[str, str]:
        """The target stage and feedback for a failing validation."""
        if verdict.replan_recommended:
            return (
                verdict.replan_target or "planning",
                "Validation found the PLAN is flawed. Revise the plan so every success "
                "criterion can be met, then re-execute.",
            )
        return (
            verdict.reject_target or "execution",
            "Validation found the result does not meet a success criterion. Fix the "
            "implementation so all criteria pass.",
        )


def _first_line(text: str) -> str:
    """The first non-empty line, with a leading 'SUMMARY:' label stripped."""
    for line in text.splitlines():
        s = line.strip()
        if s:
            return re.sub(r"^SUMMARY:\s*", "", s, flags=re.IGNORECASE)
    return ""
