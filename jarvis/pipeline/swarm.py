"""
The validation swarm — a panel of independent reviewer agents whose opinions are
consolidated by a single orchestrator agent into one decision.

Shape (the mentor's definition, followed exactly):
  * N reviewer agents, each a distinct PERSPECTIVE with its OWN hard invariants.
    Each reviews the deliverable against the plan + success criteria INDEPENDENTLY
    and never sees another reviewer's output — there is no agent-to-agent comms.
  * One consolidator agent that KNOWS the user's request (goal, plan, criteria):
    it receives every reviewer opinion and produces ONE consolidated decision —
    APPROVE / REWORK_EXECUTION / REVISE_PLAN — plus a synthesized rationale. All
    reviewer opinions flow only through this consolidator.

It plugs into the existing seam: ``SwarmStageRunner`` is a ``StageRunner``. For the
``validation`` stage (and only when enabled) it runs the panel + consolidation and
returns the consolidated TEXT, carrying the existing markers so ``ValidatorAgent``
maps it onto the 3-way human gate unchanged (it emits ``[[REPLAN]]`` for
REVISE_PLAN). For every other stage it delegates to the base ``LLMStageRunner``.

Every model call goes through the ``LLMGateway`` and is accounted onto the task,
so the swarm's spend shows up in ``task show`` and the stage header.
"""

from dataclasses import dataclass, field

from ..llm.gateway import LLMGateway
from .base import MARKER_REPLAN
from .runner import LLMStageRunner, StageRunner
from .stages import assemble_deliverable


# ── Consolidated decisions ──────────────────────────────────────────────────────
DECISION_APPROVE = "APPROVE"            # -> the human gate's "mark done" (no marker)
DECISION_REWORK = "REWORK_EXECUTION"    # -> "rework execution" (no marker)
DECISION_REVISE_PLAN = "REVISE_PLAN"    # -> "revise the plan" ([[REPLAN]] recommended)
DECISIONS = (DECISION_APPROVE, DECISION_REWORK, DECISION_REVISE_PLAN)

# The decision the consolidator's text must carry as a marker so ValidatorAgent
# maps it onto the gate. Only REVISE_PLAN has one (the gate's optional third path);
# APPROVE/REWORK are the gate's first two choices and need no marker.
_DECISION_MARKER = {DECISION_REVISE_PLAN: MARKER_REPLAN}
_DECISION_LABEL = {
    DECISION_APPROVE: "APPROVE — mark the task done",
    DECISION_REWORK: "REWORK — send back to execution",
    DECISION_REVISE_PLAN: "REVISE THE PLAN — the plan itself is at fault",
}


@dataclass(frozen=True)
class ReviewInvariant:
    """One hard rule for a reviewer's angle. A violation is a candidate FAIL."""
    id: str
    rule: str


@dataclass
class ReviewOpinion:
    """One reviewer's independent verdict (its only output; never seen by peers)."""
    perspective: str
    passed: bool
    issues: list[str] = field(default_factory=list)
    violated_invariants: list[str] = field(default_factory=list)  # ids of ITS OWN invariants
    raw: str = ""


@dataclass
class ConsolidatedReview:
    """The orchestrator's single decision and the text shown at the human gate."""
    decision: str
    rationale: str
    text: str  # human-readable consolidation, marker appended for ValidatorAgent


# ── Reviewer agent ──────────────────────────────────────────────────────────────


class ReviewerAgent:
    """One perspective on the deliverable, with its own small invariant list.

    Reviewers are independent: each is given only the task context (goal, plan,
    success criteria, deliverable) and reports pass/fail, concrete issues, and
    which of ITS OWN invariants (if any) the deliverable violates. They never see
    each other's opinions — the consolidator is the only place opinions meet.
    """

    def __init__(self, perspective: str, focus: str, invariants: list[ReviewInvariant]) -> None:
        self.perspective = perspective
        self.focus = focus
        self.invariants = invariants

    def system_prompt(self) -> str:
        rules = "\n".join(f"  - [{inv.id}] {inv.rule}" for inv in self.invariants)
        return (
            f"You are a reviewer on a validation panel. Your single perspective is "
            f"{self.perspective.upper()}: {self.focus}\n"
            "Review the deliverable ONLY from this perspective — other reviewers cover "
            "the rest. You are independent; you do not see other reviewers' opinions.\n\n"
            "Judge ONLY against the stated goal and success criteria. Do NOT invent "
            "requirements, edge cases, or constraints the user did not ask for, and do "
            "not demand scope beyond what was requested — that is itself a review error. "
            "The deliverable may contain process notes (e.g. '[step 1/3]' labels or "
            "intermediate drafts) that get assembled into the clean final result at the "
            "done stage; do not penalise those.\n\n"
            "Your hard invariants (a violation of any is a strong reason to FAIL):\n"
            f"{rules}\n\n"
            "Reply in EXACTLY this format and nothing else:\n"
            "VERDICT: PASS or FAIL\n"
            "ISSUES:\n"
            "- <one concrete issue per line, or 'none'>\n"
            "INVARIANTS_VIOLATED:\n"
            "- <invariant id of one you flag, or 'none'>"
        )

    def review_message(self, context: "_ReviewContext") -> str:
        return (
            "Review this deliverable from your perspective.\n\n"
            f"## Goal\n{context.goal or '(none stated)'}\n\n"
            f"## Success criteria\n{context.criteria or '(none stated)'}\n\n"
            f"## Plan\n{context.plan or '(none stated)'}\n\n"
            f"## Deliverable produced during execution\n{context.deliverable or '(empty)'}"
        )

    def parse_opinion(self, raw: str) -> ReviewOpinion:
        passed = True
        issues: list[str] = []
        violated: list[str] = []
        section = ""
        valid_ids = {inv.id.lower() for inv in self.invariants}
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            upper = stripped.upper()
            if upper.startswith("VERDICT:"):
                passed = "FAIL" not in upper
                section = ""
            elif upper.startswith("ISSUES:"):
                section = "issues"
            elif upper.startswith("INVARIANTS_VIOLATED:") or upper.startswith("INVARIANTS:"):
                section = "invariants"
            elif section == "issues":
                item = stripped.lstrip("-*• ").strip()
                if item and item.lower() != "none":
                    issues.append(item)
            elif section == "invariants":
                item = stripped.lstrip("-*• ").strip()
                if not item or item.lower() == "none":
                    continue
                # Accept "id: explanation" or a bare id; keep only ITS own ids.
                ident = item.split(":", 1)[0].strip().lower()
                if ident in valid_ids:
                    violated.append(ident)
        return ReviewOpinion(
            perspective=self.perspective,
            passed=passed,
            issues=issues,
            violated_invariants=violated,
            raw=raw,
        )


# ── Consolidator (orchestrator) agent ───────────────────────────────────────────


class ConsolidatorAgent:
    """The orchestrator agent: knows the user's request, weighs all opinions, decides.

    It is the ONLY place reviewer opinions meet — reviewers never argue with each
    other; they offer options to this agent, which makes one consolidated decision.
    Its own hard invariants keep the decision honest (e.g. a flagged hard-invariant
    violation forbids APPROVE).
    """

    INVARIANTS = (
        ReviewInvariant("c1", "If any reviewer flags a violated hard invariant, you must NOT APPROVE."),
        ReviewInvariant("c2", "Choose REVISE_PLAN only when the PLAN itself is at fault, not when "
                              "execution details merely need fixing."),
        ReviewInvariant("c3", "APPROVE only when the deliverable meets the goal and the success criteria."),
    )

    def system_prompt(self, context: "_ReviewContext") -> str:
        rules = "\n".join(f"  - [{inv.id}] {inv.rule}" for inv in self.INVARIANTS)
        return (
            "You are the consolidator on a validation panel. You KNOW the user's request "
            "and you receive every reviewer's independent opinion. The reviewers do not "
            "argue with each other; they only offer you options. Make ONE consolidated "
            "decision and synthesize a single rationale.\n\n"
            f"## The user's goal\n{context.goal or '(none stated)'}\n\n"
            f"## Success criteria\n{context.criteria or '(none stated)'}\n\n"
            f"## Plan\n{context.plan or '(none stated)'}\n\n"
            "Your hard invariants:\n"
            f"{rules}\n\n"
            f"Choose exactly one decision: {', '.join(DECISIONS)}.\n"
            "Reply in EXACTLY this format and nothing else:\n"
            f"DECISION: <{' | '.join(DECISIONS)}>\n"
            "RATIONALE: <2-4 sentences synthesizing the panel into your decision>"
        )

    def consolidate_message(self, opinions: list[ReviewOpinion]) -> str:
        blocks = []
        for op in opinions:
            verdict = "PASS" if op.passed else "FAIL"
            issues = "; ".join(op.issues) or "none"
            inv = ", ".join(op.violated_invariants) or "none"
            blocks.append(
                f"- {op.perspective} → {verdict}\n"
                f"    issues: {issues}\n"
                f"    invariants violated: {inv}"
            )
        return "Reviewer opinions:\n" + "\n".join(blocks) + "\n\nProduce your consolidated decision."

    def parse_decision(self, raw: str) -> tuple[str, str]:
        decision = ""
        rationale_lines: list[str] = []
        in_rationale = False
        for line in raw.splitlines():
            stripped = line.strip()
            upper = stripped.upper()
            if upper.startswith("DECISION:"):
                value = stripped.split(":", 1)[1].strip().upper().replace(" ", "_")
                for d in DECISIONS:
                    if d in value:
                        decision = d
                        break
                in_rationale = False
            elif upper.startswith("RATIONALE:"):
                rationale_lines.append(stripped.split(":", 1)[1].strip())
                in_rationale = True
            elif in_rationale and stripped:
                rationale_lines.append(stripped)
        # Default safely to REWORK (never auto-approve on an unparseable reply).
        if not decision:
            decision = DECISION_REWORK
        return decision, "\n".join(rationale_lines).strip()

    def build_review(self, decision: str, rationale: str, opinions: list[ReviewOpinion]) -> ConsolidatedReview:
        """Assemble the human-facing consolidation text and append the gate marker."""
        passed = sum(1 for op in opinions if op.passed)
        header = (
            f"Validation swarm — {len(opinions)} reviewers, {passed} passed.\n"
            f"Recommendation: {_DECISION_LABEL[decision]}."
        )
        breakdown = "\n".join(
            f"  • {op.perspective}: {'PASS' if op.passed else 'FAIL'}"
            + (f" (issues: {'; '.join(op.issues)})" if op.issues else "")
            + (f" [invariants: {', '.join(op.violated_invariants)}]" if op.violated_invariants else "")
            for op in opinions
        )
        text = f"{header}\n\n{rationale}\n\nPanel breakdown:\n{breakdown}".rstrip()
        marker = _DECISION_MARKER.get(decision)
        if marker:
            text = f"{text}\n\n{marker}"
        return ConsolidatedReview(decision=decision, rationale=rationale, text=text)


# ── Review context (the deliverable + what to check it against) ──────────────────


@dataclass
class _ReviewContext:
    goal: str
    criteria: str
    plan: str
    deliverable: str

    @classmethod
    def from_task(cls, task: dict) -> "_ReviewContext":
        outputs = task.get("stage_outputs") or {}
        return cls(
            goal=task.get("description") or "",
            criteria=outputs.get("clarification") or "",
            plan=task.get("plan") or "",
            deliverable=assemble_deliverable(outputs.get("execution") or ""),
        )


# ── Default panel (5 perspectives, each with its own invariants) ─────────────────


def default_reviewers() -> list[ReviewerAgent]:
    """The default panel. Jarvis handles general tasks, so the angles are general,
    but each carries hard invariants for its perspective."""
    return [
        ReviewerAgent(
            "Correctness",
            "is the deliverable factually and logically correct?",
            [
                ReviewInvariant("corr-1", "A factual or logical error in the deliverable is a FAIL."),
                ReviewInvariant("corr-2", "A deliverable that contradicts itself is a FAIL."),
            ],
        ),
        ReviewerAgent(
            "Goal fit",
            "does the deliverable actually satisfy the stated goal and success criteria?",
            [
                ReviewInvariant("goal-1", "A deliverable that does not address the stated goal is a FAIL."),
                ReviewInvariant("goal-2", "Any explicit success criterion left unmet is a FAIL."),
            ],
        ),
        ReviewerAgent(
            "Completeness",
            "is every part of the planned work present in the deliverable?",
            [
                ReviewInvariant("comp-1", "A plan step with no corresponding output in the deliverable is a FAIL."),
                ReviewInvariant("comp-2", "Any placeholder, TODO, or '...' left in a final deliverable is a FAIL."),
            ],
        ),
        ReviewerAgent(
            "Robustness",
            "are the constraints and edge cases THE USER STATED handled?",
            [
                ReviewInvariant("robu-1", "A constraint or edge case EXPLICITLY STATED in the goal or "
                                          "success criteria that is left unhandled is a FAIL. Do NOT "
                                          "invent edge cases or failure modes the user did not ask for."),
            ],
        ),
        ReviewerAgent(
            "Clarity",
            "is the deliverable's CONTENT clear and coherent for its intended reader?",
            [
                ReviewInvariant("clar-1", "Content whose substance cannot be understood by its "
                                          "intended reader is a FAIL. Ignore process scaffolding "
                                          "(step labels, intermediate drafts) — those are assembled "
                                          "into the clean final deliverable at the done stage."),
            ],
        ),
    ]


# ── The StageRunner that fans validation out to the swarm ────────────────────────


class SwarmStageRunner:
    """A ``StageRunner`` that swarms the validation stage and delegates the rest.

    For ``validation`` (when ``review_agents`` > 1) it runs the reviewer panel
    independently, consolidates the opinions into one decision, accounts every
    call onto the task, persists the consolidated turn, and returns the text with
    its gate marker. For any other stage — or when the swarm is off — it delegates
    to the wrapped ``LLMStageRunner`` unchanged.
    """

    def __init__(
        self,
        gateway: LLMGateway,
        config,
        base_runner: StageRunner,
        tasks,
        reviewers: list[ReviewerAgent] | None = None,
        consolidator: ConsolidatorAgent | None = None,
    ) -> None:
        self._gateway = gateway
        self._config = config
        self._base = base_runner
        self._tasks = tasks
        self._reviewers = reviewers if reviewers is not None else default_reviewers()
        self._consolidator = consolidator or ConsolidatorAgent()

    def run(self, task: dict, entry_message: str, extra_system: str = "") -> str:
        n = int(self._config.runtime.get("review_agents", 1) or 1)
        if task.get("stage") != "validation" or n <= 1:
            return self._base.run(task, entry_message, extra_system)

        panel = self._reviewers[: min(n, len(self._reviewers))]
        context = _ReviewContext.from_task(task)
        params = self._params()
        api_calls: list[dict] = []

        opinions = self._gather_opinions(panel, context, params, api_calls)

        # The consolidator (orchestrator) is the ONLY place opinions meet.
        cons_messages = [
            {"role": "system", "content": self._consolidator.system_prompt(context)},
            {"role": "user", "content": self._consolidator.consolidate_message(opinions)},
        ]
        cons = self._gateway.complete(cons_messages, params, label="swarm_consolidator", api_calls=api_calls)
        decision, rationale = self._consolidator.parse_decision(cons.text)
        review = self._consolidator.build_review(decision, rationale, opinions)

        # Every reviewer + the consolidator call is billed to the task (same shape
        # as LLMStageRunner), so the swarm's spend shows in `task show`.
        LLMStageRunner._account(task, api_calls)

        history = task.setdefault("messages", [])
        history.append({"role": "user", "content": entry_message})
        history.append({"role": "assistant", "content": review.text})
        self._tasks.save(task)
        return review.text

    def _gather_opinions(self, panel, context, params, api_calls) -> list[ReviewOpinion]:
        """Run the panel concurrently — reviewers are independent, so there is no
        reason to serialise them. Accounting stays deterministic regardless of
        completion order (each call records into its own bucket, merged in panel
        order below), so tests remain stable."""
        from concurrent.futures import ThreadPoolExecutor

        # Each reviewer call mints its own private api_calls list (the gateway's
        # sequential index is per-list), merged in order afterwards so accounting
        # stays deterministic regardless of completion order.
        buckets: list[list[dict]] = [[] for _ in panel]

        def _work(i_reviewer):
            i, reviewer = i_reviewer
            return i, self._review_one(reviewer, context, params, buckets[i])

        with ThreadPoolExecutor(max_workers=len(panel)) as pool:
            results = list(pool.map(_work, enumerate(panel)))
        results.sort(key=lambda r: r[0])
        for bucket in buckets:
            for record in bucket:
                record["index"] = len(api_calls) + 1
                api_calls.append(record)
        return [op for _, op in results]

    def _review_one(self, reviewer, context, params, api_calls) -> ReviewOpinion:
        messages = [
            {"role": "system", "content": reviewer.system_prompt()},
            {"role": "user", "content": reviewer.review_message(context)},
        ]
        completion = self._gateway.complete(
            messages, params, label=f"swarm_reviewer:{reviewer.perspective}", api_calls=api_calls
        )
        return reviewer.parse_opinion(completion.text)

    def _params(self) -> dict:
        # Mirror the InvariantChecker: only the model matters for these short,
        # structured calls; avoid inheriting unrelated generation params.
        runtime = self._config.runtime
        return {"model": runtime["model"]} if "model" in runtime else {}
