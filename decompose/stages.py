"""The stage vocabulary: enums, the ``Features`` carrier, prompts, and parsers.

Shared by both options so the monolithic call and the pipeline agree on exactly
one label set, one feature schema and one result shape — the only thing that
differs between A and B is how many requests produce them.

Every stage output is *strict*: a fixed enum, or a compact ``key: value`` block.
Strictness is the point of decomposition — a stage that can only emit one of four
labels cannot wander, and its parser rejects anything else as ``None`` (a failure
the harness can see) rather than smuggling free text downstream.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from finetune.common import LABELS
from jarvis.llm.accounting import make_call_record
from jarvis.openrouter.client import Completion

# ── Stage-1 enums (analysis / normalization) ─────────────────────────────────

SENDERS = ("person", "automated", "marketing")
DEADLINES = ("now", "today", "this_week", "none")
IMPORTANCE = ("high", "medium", "low")

# Label → the action Stage 3 attaches. A fixed table, not a model guess: the map
# from priority to what-to-do is a business rule, so it stays deterministic.
ACTIONS = {
    "urgent_now": "notify_now",
    "today": "add_to_today",
    "this_week": "add_to_backlog",
    "ignore": "archive",
}


@dataclass
class Features:
    sender: str            # person | automated | marketing
    action_required: bool  # does it need the reader to do something?
    deadline: str          # now | today | this_week | none
    importance: str        # high | medium | low


@dataclass
class Outcome:
    method: str               # "monolithic" | "multistage"
    label: str | None         # the priority label, or None if any stage failed strictly
    features: Features | None  # extracted features (both options produce them)
    action: str | None        # ACTIONS[label], or None
    why: str | None           # one-line rationale (Stage 3 / the monolithic "why")
    n_calls: int              # requests spent (1 for A, up to 3 for B)
    latency_ms: float         # summed wall-clock across the calls
    cost_usd: float | None    # summed cost, or None if pricing unavailable
    completions: list[Completion] = field(repr=False)  # raw calls, for accounting/debug


# ── Prompts ──────────────────────────────────────────────────────────────────

ANALYZE_SYSTEM = (
    "You extract structured features from one incoming message. Choose exactly one "
    "allowed value for each field — never copy the list of options.\n"
    "Allowed values:\n"
    "- sender: person, automated, or marketing (a real person, an automated "
    "system/notification, or a marketing/promotion).\n"
    "- action_required: yes or no (does it need the reader to do something?).\n"
    "- deadline: now, today, this_week, or none (how soon any action is needed).\n"
    "- importance: high, medium, or low (how important the topic is to the reader).\n"
    "Reply with ONLY a compact JSON object, no code fence. Two examples of the exact shape:\n"
    '{"sender": "person", "action_required": "yes", "deadline": "now", "importance": "high"}\n'
    '{"sender": "marketing", "action_required": "no", "deadline": "none", "importance": "low"}\n'
    "Output one such JSON object and nothing more."
)

DECIDE_SYSTEM = (
    "You assign a priority label from the given features. Reply with exactly one "
    "label and nothing else: urgent_now, today, this_week, or ignore.\n"
    "- urgent_now: action required and deadline now, or high-importance needing immediate attention.\n"
    "- today: action required with a today deadline, or important but not instant.\n"
    "- this_week: action or follow-up needed this week, lower urgency.\n"
    "- ignore: no action required — marketing, automated notifications, or low importance.\n"
    "Output only the label."
)

GENERATE_SYSTEM = (
    "Write one short sentence, at most 15 words, explaining why this message has "
    "the given priority label. Output only the sentence, no label, no quotes."
)


# ── Parsers (strict) ─────────────────────────────────────────────────────────

_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("yes", "true", "1"):
            return True
        if low in ("no", "false", "0"):
            return False
    return None


def parse_features(text: str) -> Features | None:
    """Strict parse of a Stage-1 reply → ``Features`` or ``None`` on any violation."""
    match = _OBJECT.search(text)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    sender = obj.get("sender")
    deadline = obj.get("deadline")
    importance = obj.get("importance")
    action_required = _as_bool(obj.get("action_required"))
    if sender not in SENDERS or deadline not in DEADLINES or importance not in IMPORTANCE:
        return None
    if action_required is None:
        return None
    return Features(sender=sender, action_required=action_required,
                    deadline=deadline, importance=importance)


def parse_label(text: str) -> str | None:
    """First known label in the reply, or ``None`` — the strict enum gate."""
    stripped = text.strip()
    if stripped in LABELS:
        return stripped
    for label in LABELS:  # tolerate a stray word around the label
        if label in stripped:
            return label
    return None


def render_features(f: Features) -> str:
    """Compact ``key: value`` block — the strict, token-light Stage-2 input."""
    return (f"sender: {f.sender}\n"
            f"action_required: {'yes' if f.action_required else 'no'}\n"
            f"deadline: {f.deadline}\n"
            f"importance: {f.importance}")


# ── Call helper ──────────────────────────────────────────────────────────────

def ask(engine, model: str, system: str, user: str, temperature: float, max_tokens: int) -> Completion:
    """One short request. A provider/network failure returns an empty errored
    completion rather than raising, so one bad case never aborts the batch."""
    params: dict = {"model": model, "temperature": temperature, "max_tokens": max_tokens}
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    t0 = time.perf_counter()
    try:
        return engine.complete(messages, params)
    except Exception:  # noqa: BLE001 — any failure is a strict-parse failure downstream
        return Completion(text="", finish_reason="error", request={"model": model, "messages": messages},
                          response={}, latency_ms=(time.perf_counter() - t0) * 1000)


def account(completions: list[Completion], engine) -> tuple[float, float | None]:
    """Sum latency and cost across an outcome's calls (one engine, per-stage models)."""
    latency = sum(c.latency_ms for c in completions)
    costs = [make_call_record(i, "decompose", c, engine)["cost"]["total_usd"]
             for i, c in enumerate(completions)]
    known = [c for c in costs if c is not None]
    return latency, (sum(known) if known else None)
