"""The escalation policy and the routing orchestration.

``decide`` is a pure function of one cheap answer plus thresholds, so the whole
routing rule is unit-testable without a network. ``route`` runs the cheap tier,
applies ``decide``, and — only when it says so — spends a second call on the
strong tier, returning both the served answer and a full record of why.

The fusion rule, using the two heuristics together:

* confidence **below** ``conf_low``           → escalate (clearly unsure).
* confidence in ``[conf_low, conf_high)``      → middle band: escalate only if a
  length signal corroborates (hedged, or shorter than ``min_words``).
* confidence **at/above** ``conf_high``        → keep, unless the text hedges while
  claiming high confidence (a self-contradiction) → escalate.
* no usable confidence, or an unparseable/failed cheap reply → escalate.

So the self-score is primary and length is a corroborator. That ordering is on
purpose: raw length alone is a poor signal — a correct "4" to "2+2" is short and
certain — so length only counts when the score is already lukewarm.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.llm.accounting import make_call_record

from .answer import AnswerRun, answer
from .heuristics import is_hedged, word_count
from .runtime import Tiers


@dataclass
class Config:
    # Band sits high on purpose: a small model's self-scores cluster near 1.0
    # (it is overconfident), so a textbook 0.5/0.75 band would never fire. These
    # were calibrated to where qwen2.5:3b actually separates sure from unsure.
    conf_low: float = 0.6     # below this, escalate outright
    conf_high: float = 0.85   # at/above this, keep unless the text contradicts the score
    min_words: int = 4        # in the middle band, an answer this short corroborates escalation
    temperature: float = 0.0  # deterministic answers → reproducible routing decisions
    max_tokens: int = 400     # room for a real answer, not just a label


@dataclass
class Decision:
    escalate: bool         # route on to the strong tier?
    reasons: list[str]     # which rules fired (empty when kept on cheap)
    signals: dict          # the raw signals read: confidence, words, hedged


@dataclass
class RouteResult:
    query: str
    served_by: str            # "cheap" | "strong" — which tier's answer is returned
    escalated: bool
    reasons: list[str]        # why it escalated (empty if it did not)
    signals: dict             # cheap-tier signals that drove the decision
    final_answer: str | None  # the answer served to the caller
    final_confidence: float | None
    cheap_answer: str | None      # what the cheap tier said (kept for the report)
    cheap_confidence: float | None
    strong_answer: str | None     # None when not escalated
    n_calls: int              # inference calls spent (1 kept, 2 escalated)
    latency_ms: float         # summed wall-clock across the calls
    cost_usd: float | None    # summed cost, or None if pricing unavailable
    runs: list[AnswerRun] = field(repr=False)


def decide(run: AnswerRun, cfg: Config) -> Decision:
    """Pure escalation policy → whether to route the query to the strong tier."""
    if run.answer is None:
        why = "cheap_error" if run.error is not None else "cheap_unparseable"
        return Decision(True, [why], {"confidence": run.confidence, "words": 0, "hedged": False})

    words = word_count(run.answer)
    hedged = is_hedged(run.answer)
    conf = run.confidence
    signals = {"confidence": conf, "words": words, "hedged": hedged}
    reasons: list[str] = []

    if conf is None:
        reasons.append("no_confidence")
    elif conf < cfg.conf_low:
        reasons.append(f"low_confidence<{cfg.conf_low}")
    elif conf < cfg.conf_high:  # middle band: needs a corroborating length signal
        if hedged:
            reasons.append("hedged")
        if words < cfg.min_words:
            reasons.append("too_short")
    elif hedged:  # high score but the text admits doubt — trust the words
        reasons.append("hedged_despite_high_confidence")

    return Decision(bool(reasons), reasons, signals)


def _accounting(pairs: list[tuple[AnswerRun, object]]) -> tuple[float, float | None]:
    """Sum latency and cost across the calls, each priced by its own engine."""
    latency = sum(r.completion.latency_ms for r, _ in pairs)
    costs = [make_call_record(i, "routing", r.completion, eng)["cost"]["total_usd"]
             for i, (r, eng) in enumerate(pairs)]
    known = [c for c in costs if c is not None]
    return latency, (sum(known) if known else None)


def route(tiers: Tiers, query: str, cfg: Config | None = None) -> RouteResult:
    """Route one query: cheap tier first, escalate to strong on an uncertain answer."""
    cfg = cfg or Config()
    cheap = tiers.cheap
    cheap_run = answer(cheap.engine, cheap.model, query, cfg.temperature, cfg.max_tokens)
    decision = decide(cheap_run, cfg)

    pairs: list[tuple[AnswerRun, object]] = [(cheap_run, cheap.engine)]
    strong_run: AnswerRun | None = None
    if decision.escalate:
        strong = tiers.strong
        strong_run = answer(strong.engine, strong.model, query, cfg.temperature, cfg.max_tokens)
        pairs.append((strong_run, strong.engine))

    final = strong_run if strong_run is not None else cheap_run
    latency, cost = _accounting(pairs)
    return RouteResult(
        query=query,
        served_by="strong" if decision.escalate else "cheap",
        escalated=decision.escalate,
        reasons=decision.reasons,
        signals=decision.signals,
        final_answer=final.answer,
        final_confidence=final.confidence,
        cheap_answer=cheap_run.answer,
        cheap_confidence=cheap_run.confidence,
        strong_answer=strong_run.answer if strong_run is not None else None,
        n_calls=len(pairs),
        latency_ms=latency,
        cost_usd=cost,
        runs=[r for r, _ in pairs],
    )
