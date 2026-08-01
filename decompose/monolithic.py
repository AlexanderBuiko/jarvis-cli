"""Option A — the monolithic path: one big request, one answer.

The whole job (extract features, decide the label, name the action and reason) is
asked for in a single call that must return one JSON object. This is the baseline
the decomposition is measured against: it is cheap in calls (exactly one) but asks
the model to juggle extraction, a conditional decision and generation at once —
the load that a small model handles poorly.
"""

from __future__ import annotations

import json

from .stages import ACTIONS, Features, Outcome, account, ask
from .stages import DEADLINES, IMPORTANCE, SENDERS, _OBJECT, _as_bool
from finetune.common import LABELS

MONO_SYSTEM = (
    "You are a message-priority assistant. Read the incoming message and do the "
    "whole job in one step: extract its features, decide its priority label, and "
    "name the action. Choose exactly one allowed value per field — never copy the "
    "list of options.\n"
    "Allowed values:\n"
    "- sender: person, automated, or marketing.\n"
    "- action_required: yes or no.\n"
    "- deadline: now, today, this_week, or none.\n"
    "- importance: high, medium, or low.\n"
    "- label: urgent_now, today, this_week, or ignore.\n"
    "- action: notify_now, add_to_today, add_to_backlog, or archive.\n"
    "- why: one short reason, at most 15 words.\n"
    "Reply with ONLY a compact JSON object, no code fence. Example of the exact shape:\n"
    '{"sender": "person", "action_required": "yes", "deadline": "now", "importance": "high", '
    '"label": "urgent_now", "action": "notify_now", "why": "boss needs the deck before the call"}\n'
    "Output one such JSON object and nothing more."
)


def _features_from(obj: dict) -> Features | None:
    sender, deadline, importance = obj.get("sender"), obj.get("deadline"), obj.get("importance")
    action_required = _as_bool(obj.get("action_required"))
    if sender not in SENDERS or deadline not in DEADLINES or importance not in IMPORTANCE:
        return None
    if action_required is None:
        return None
    return Features(sender, action_required, deadline, importance)


def run_monolithic(engine, model: str, user_content: str, temperature: float) -> Outcome:
    """Classify in one big request and parse the whole result out of one reply."""
    completion = ask(engine, model, MONO_SYSTEM, user_content, temperature, max_tokens=200)
    label = why = action = None
    features = None
    match = _OBJECT.search(completion.text)
    if match:
        try:
            obj = json.loads(match.group(0))
        except (ValueError, TypeError):
            obj = {}
        raw_label = obj.get("label")
        label = raw_label if raw_label in LABELS else None
        features = _features_from(obj)
        why = obj.get("why") if isinstance(obj.get("why"), str) else None
        # Trust the fixed table over the model's self-named action.
        action = ACTIONS.get(label) if label else None
    latency, cost = account([completion], engine)
    return Outcome(method="monolithic", label=label, features=features, action=action, why=why,
                   n_calls=1, latency_ms=latency, cost_usd=cost, completions=[completion])
