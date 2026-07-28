"""One scored classification call: a label plus the model's own confidence.

This is the single primitive both mechanisms share. Each call asks the model for
a compact JSON object ``{"label": ..., "confidence": ...}``; running it N times
gives the *redundancy* vote, and the per-run confidence gives the *scoring*
signal. Parsing is defensive — a malformed reply becomes ``label=None`` rather
than an exception, because "the model returned garbage" is itself a confidence
signal the fuser must see (it drives a FAIL), not an error to crash on.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from finetune.common import LABELS
from jarvis.openrouter.client import Completion

# A scoring-specific system prompt: same task as the Day-6 classifier, but the
# reply carries a self-assessed confidence. The label set is stated inline so a
# small local model has the vocabulary in front of it.
_SCORING_SYSTEM = (
    "You are a message-priority classifier. Read the incoming message and decide "
    "its priority: urgent_now, today, this_week, or ignore.\n"
    "Reply with ONLY a compact JSON object and nothing else, no code fence:\n"
    '{"label": "<one of the four>", "confidence": <number between 0 and 1>}\n'
    "confidence is how sure you are of the label. Output the JSON and nothing more."
)

_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class ScoredRun:
    label: str | None         # parsed priority label, or None if unparseable/invalid
    confidence: float | None  # model's self-reported confidence 0..1, or None
    text: str                 # raw assistant text, kept for debugging a bad parse
    completion: Completion    # full engine result, for latency/cost accounting
    error: str | None = None  # provider refusal (e.g. content filter) or network failure


def _parse(text: str) -> tuple[str | None, float | None]:
    """Extract (label, confidence) from a reply, tolerating stray prose/fences."""
    match = _OBJECT.search(text)
    if not match:
        return None, None
    try:
        obj = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None, None
    label = obj.get("label")
    if label not in LABELS:
        label = None
    try:
        confidence: float | None = max(0.0, min(1.0, float(obj.get("confidence"))))
    except (TypeError, ValueError):
        confidence = None
    return label, confidence


def classify_scored(
    engine, model: str, user_content: str, temperature: float, seed: int | None = None
) -> ScoredRun:
    """Run one scored classification and return the parsed result plus raw call.

    A provider error — a content filter refusing the prompt, a timeout, a network
    blip — is caught and returned as an errored run (``label=None``), not raised.
    For a quality-control layer that is signal, not a crash: a refusal means we
    cannot trust an answer, so it flows into the FAIL path like any other invalid
    reply, and one bad input never aborts a whole batch.
    """
    params: dict = {"model": model, "temperature": temperature, "max_tokens": 60}
    if seed is not None:
        params["seed"] = seed
    messages = [
        {"role": "system", "content": _SCORING_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    t0 = time.perf_counter()
    try:
        completion = engine.complete(messages, params)
    except Exception as exc:  # noqa: BLE001 — any provider/network failure is a low-confidence signal
        empty = Completion(text="", finish_reason="error", request={"model": model, "messages": messages},
                           response={}, latency_ms=(time.perf_counter() - t0) * 1000)
        return ScoredRun(label=None, confidence=None, text="", completion=empty, error=str(exc))
    label, confidence = _parse(completion.text)
    return ScoredRun(label=label, confidence=confidence, text=completion.text, completion=completion)
