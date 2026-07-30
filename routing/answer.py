"""One answer call that also carries the model's own confidence.

The single primitive both tiers share. The model is asked for a compact JSON
object ``{"answer": ..., "confidence": ...}`` so a general-purpose answer and a
self-assessed confidence come back in one call — the cheap path stays one call.
Parsing is defensive: a malformed or refused reply becomes ``answer=None`` rather
than an exception, because "the cheap model returned garbage" is itself a reason
to escalate, not an error to crash on.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from jarvis.openrouter.client import Completion

# Ask for a natural answer plus an honest self-score. Stating the JSON shape inline
# keeps a small local model on format; "be honest / use a low value" pushes it to
# actually vary the score instead of always saying 1.0.
_ANSWER_SYSTEM = (
    "You are a helpful assistant. Answer the user's question as accurately and "
    "completely as you can.\n"
    "Reply with ONLY a compact JSON object and nothing else, no code fence:\n"
    '{"answer": "<your answer as a plain string>", "confidence": <number between 0 and 1>}\n'
    "confidence is how sure you are that your answer is correct and complete. Be "
    "honest: use a low value when the question is ambiguous, outside your "
    "knowledge, or you are guessing. Output the JSON and nothing more."
)

_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class AnswerRun:
    answer: str | None        # parsed answer text, or None if unparseable/refused
    confidence: float | None  # model's self-reported confidence 0..1, or None
    text: str                 # raw assistant text, kept for debugging a bad parse
    completion: Completion    # full engine result, for latency/cost accounting
    error: str | None = None  # provider refusal (content filter) or network failure


def _parse(text: str) -> tuple[str | None, float | None]:
    """Extract (answer, confidence) from a reply, tolerating stray prose/fences."""
    match = _OBJECT.search(text)
    if not match:
        return None, None
    try:
        obj = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None, None
    answer = obj.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        answer = None
    try:
        confidence: float | None = max(0.0, min(1.0, float(obj.get("confidence"))))
    except (TypeError, ValueError):
        confidence = None
    return (answer.strip() if answer else None), confidence


def answer(engine, model: str, query: str, temperature: float, max_tokens: int) -> AnswerRun:
    """Run one answer call and return the parsed result plus the raw completion.

    A provider error — a content filter, a timeout, an unreachable daemon — is
    caught and returned as an errored run (``answer=None``), not raised. For the
    router that is a routing signal: a cheap tier that fails escalates to the
    strong tier like any other low-confidence result, and one bad query never
    aborts the whole batch.
    """
    params: dict = {"model": model, "temperature": temperature, "max_tokens": max_tokens}
    messages = [
        {"role": "system", "content": _ANSWER_SYSTEM},
        {"role": "user", "content": query},
    ]
    t0 = time.perf_counter()
    try:
        completion = engine.complete(messages, params)
    except Exception as exc:  # noqa: BLE001 — any provider/network failure is an escalation signal
        empty = Completion(text="", finish_reason="error", request={"model": model, "messages": messages},
                           response={}, latency_ms=(time.perf_counter() - t0) * 1000)
        return AnswerRun(answer=None, confidence=None, text="", completion=empty, error=str(exc))
    parsed_answer, confidence = _parse(completion.text)
    return AnswerRun(answer=parsed_answer, confidence=confidence, text=completion.text, completion=completion)
