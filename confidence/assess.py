"""Fuse redundancy + scoring into an accept/reject verdict.

``fuse`` is a pure function of the runs and thresholds, so the whole decision
policy is unit-testable without a network. ``assess`` orchestrates the calls,
the optional re-inference on UNSURE, and the latency/cost accounting.

Verdict meaning:
* **OK** — full agreement across runs *and* confident: accept automatically.
* **UNSURE** — a majority exists but agreement or confidence is soft: reject,
  route to a human (or escalate for another round).
* **FAIL** — no majority, or every reply was malformed, or confidence is below
  the floor: reject hard.

Only OK is accepted; UNSURE and FAIL are the rejections the assignment measures.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from jarvis.llm.accounting import make_call_record

from .classify import ScoredRun, classify_scored

VERDICTS = ("OK", "UNSURE", "FAIL")


@dataclass
class Config:
    n: int = 3                # redundancy samples per input
    temperature: float = 0.6  # >0 so runs can disagree (self-consistency needs spread)
    conf_high: float = 0.75   # mean confidence at/above this is "confident"
    conf_low: float = 0.40    # mean confidence below this rejects outright
    escalate: bool = False    # on UNSURE, sample another round before deciding
    escalate_n: int = 3       # extra samples when escalating
    seed_base: int = 1000     # per-run seeds, so a run is reproducible


@dataclass
class Assessment:
    verdict: str              # OK | UNSURE | FAIL
    label: str | None         # best-guess majority label, even when rejected
    agreement: float          # winning-label votes / total samples
    mean_confidence: float | None
    n_calls: int              # total inference calls spent (incl. escalation)
    n_errors: int             # calls that errored (content filter / network) — a FAIL signal
    escalated: bool           # did an UNSURE trigger a second round?
    latency_ms: float         # summed wall-clock across all calls
    cost_usd: float | None    # summed cost, or None if pricing unavailable
    runs: list[ScoredRun] = field(repr=False)

    @property
    def accepted(self) -> bool:
        return self.verdict == "OK"


def fuse(runs: list[ScoredRun], cfg: Config) -> tuple[str, str | None, float, float | None]:
    """Pure decision policy → (verdict, label, agreement, mean_confidence)."""
    n = len(runs)
    valid = [r for r in runs if r.label is not None]
    if not valid:
        return "FAIL", None, 0.0, None  # constraint gate: everything malformed

    votes = Counter(r.label for r in valid)
    label, win = votes.most_common(1)[0]
    agreement = win / n if n else 0.0
    winner_conf = [r.confidence for r in valid if r.label == label and r.confidence is not None]
    mean_conf = sum(winner_conf) / len(winner_conf) if winner_conf else None

    if win * 2 <= n:  # no strict majority (e.g. 1/1/1, or a malformed-diluted tie)
        return "FAIL", label, agreement, mean_conf
    if mean_conf is not None and mean_conf < cfg.conf_low:
        return "FAIL", label, agreement, mean_conf
    if agreement >= 1.0 and (mean_conf is None or mean_conf >= cfg.conf_high):
        return "OK", label, agreement, mean_conf
    return "UNSURE", label, agreement, mean_conf


def _sample(engine, model: str, user_content: str, cfg: Config, start: int, count: int) -> list[ScoredRun]:
    return [
        classify_scored(engine, model, user_content, cfg.temperature, cfg.seed_base + start + i)
        for i in range(count)
    ]


def _accounting(runs: list[ScoredRun], engine) -> tuple[float, float | None]:
    latency = sum(r.completion.latency_ms for r in runs)
    costs = [make_call_record(i, "confidence", r.completion, engine)["cost"]["total_usd"]
             for i, r in enumerate(runs)]
    known = [c for c in costs if c is not None]
    return latency, (sum(known) if known else None)


def assess(engine, model: str, user_content: str, cfg: Config | None = None) -> Assessment:
    """Classify with redundancy + scoring and return an accept/reject verdict."""
    cfg = cfg or Config()
    runs = _sample(engine, model, user_content, cfg, 0, cfg.n)
    verdict, label, agreement, mean_conf = fuse(runs, cfg)

    escalated = False
    if cfg.escalate and verdict == "UNSURE":
        runs += _sample(engine, model, user_content, cfg, len(runs), cfg.escalate_n)
        verdict, label, agreement, mean_conf = fuse(runs, cfg)
        escalated = True

    latency, cost = _accounting(runs, engine)
    return Assessment(
        verdict=verdict, label=label, agreement=agreement, mean_confidence=mean_conf,
        n_calls=len(runs), n_errors=sum(1 for r in runs if r.error), escalated=escalated,
        latency_ms=latency, cost_usd=cost, runs=runs,
    )
