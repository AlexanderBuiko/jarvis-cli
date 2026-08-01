"""The two-tier route: micro-model first, big LLM only on UNSURE.

``route`` is the whole policy. It always runs the micro-model (Tier 1); it calls
the big model (Tier 2) *only* when the micro-model is UNSURE — the confidence-below-
threshold trigger. A malformed micro answer would be the third trigger the brief
lists, but the embedding classifier always returns a valid label, so UNSURE is the
only gate here.

The result records which tier answered, so the harness can report how much traffic
the micro-model absorbed and how many big-LLM calls were actually spent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from jarvis.llm.accounting import make_call_record
from finetune.common import SYSTEM_PROMPT
from decompose.stages import ask, parse_label

from .micro import MicroClassifier, MicroResult


@dataclass
class TwoTierResult:
    query: str
    reference: str | None    # gold label when known, else None
    label: str | None        # served label
    tier: str                # "micro" | "llm"
    micro: MicroResult       # the Tier-1 result (kept even when escalated)
    escalated: bool          # did it fall back to the big LLM?
    n_llm_calls: int         # 0 when the micro-model handled it, 1 on fallback
    latency_ms: float        # wall-clock for the whole route (embedding + any LLM)
    cost_usd: float | None   # big-LLM cost, or 0.0 when it never ran


def route(micro: MicroClassifier, engine, model: str, query: str, temperature: float,
          reference: str | None = None) -> TwoTierResult:
    """Classify with the micro-model; fall back to the big LLM only if UNSURE."""
    t0 = time.perf_counter()
    m = micro.classify(query)

    label: str | None = m.label
    tier, n_llm, cost = "micro", 0, 0.0
    if m.status != "OK":
        completion = ask(engine, model, SYSTEM_PROMPT, query, temperature, max_tokens=8)
        label = parse_label(completion.text)
        tier, n_llm = "llm", 1
        cost = make_call_record(0, "microfirst", completion, engine)["cost"]["total_usd"]

    latency = (time.perf_counter() - t0) * 1000
    return TwoTierResult(query=query, reference=reference, label=label, tier=tier, micro=m,
                         escalated=(tier == "llm"), n_llm_calls=n_llm, latency_ms=latency, cost_usd=cost)
