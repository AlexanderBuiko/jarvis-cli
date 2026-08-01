"""Option B — the multi-stage pipeline: three short, strict-format requests.

The same job as ``monolithic`` split into stages, each with a narrow contract:

1. **analyze** — raw message → ``Features`` (enums only). The model does one thing:
   read text, emit structured fields.
2. **decide** — ``Features`` → one label. It never sees the raw message, only the
   normalized features, so the decision is a clean mapping over a tiny input. This
   is the stage worth pointing at a stronger model (``models["decide"]``).
3. **generate** — label + features → a one-line reason; the action comes from the
   fixed ``ACTIONS`` table.

A stage that fails its strict parse short-circuits: the pipeline stops and returns
what it has, with ``label=None`` and the calls actually spent. That keeps the cost
honest and makes a failure visible instead of guessed-around.
"""

from __future__ import annotations

from .stages import (
    ACTIONS, DECIDE_SYSTEM, GENERATE_SYSTEM, ANALYZE_SYSTEM, Outcome,
    account, ask, parse_features, parse_label, render_features,
)
from finetune.common import SYSTEM_PROMPT


def run_multistage(engine, models: dict[str, str], user_content: str, temperature: float,
                   tuned_decide: str | None = None) -> Outcome:
    """Run analyze → decide → generate, short-circuiting on the first strict failure.

    ``tuned_decide`` points the decision stage at a model **fine-tuned for this
    classification** — the Day-6 adapter, exported to Ollama. Because that model
    was trained on the raw message → label task, it classifies the message
    directly (its native input) instead of the extracted features; the Stage-1
    features still feed generation. This is the "strengthen the pipe pointwise"
    move: one specialised stage, the others left as cheap base models.
    """
    completions = []

    c1 = ask(engine, models["analyze"], ANALYZE_SYSTEM, user_content, temperature, max_tokens=120)
    completions.append(c1)
    features = parse_features(c1.text)
    if features is None:
        return _outcome(None, None, None, None, completions, engine)

    if tuned_decide:
        c2 = ask(engine, tuned_decide, SYSTEM_PROMPT, user_content, temperature, max_tokens=8)
    else:
        c2 = ask(engine, models["decide"], DECIDE_SYSTEM, render_features(features), temperature, max_tokens=8)
    completions.append(c2)
    label = parse_label(c2.text)
    if label is None:
        return _outcome(None, features, None, None, completions, engine)

    c3 = ask(engine, models["generate"], GENERATE_SYSTEM,
             f"label: {label}\n{render_features(features)}", temperature, max_tokens=40)
    completions.append(c3)
    why = c3.text.strip() or None
    return _outcome(label, features, ACTIONS.get(label), why, completions, engine)


def _outcome(label, features, action, why, completions, engine) -> Outcome:
    latency, cost = account(completions, engine)
    return Outcome(method="multistage", label=label, features=features, action=action, why=why,
                   n_calls=len(completions), latency_ms=latency, cost_usd=cost, completions=completions)
