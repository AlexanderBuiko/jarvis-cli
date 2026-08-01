"""Day-9 inference decomposition — one big request vs a three-stage pipeline.

Takes a task a single query solves poorly — the Day-6 message-priority classifier
(complex classification + multi-field extraction + a conditional decision, ~38% on
a small local model) — and contrasts two ways to run it:

* **Option A — monolithic**: one big request does the whole job at once (extract
  the features, decide the label, name the action) and returns one JSON answer.
* **Option B — multi-stage**: the same job split into three short, strict-format
  calls —
    1. **analyze / normalize** → structured features, enums only;
    2. **decide / classify** → one priority label, chosen from the features alone;
    3. **generate** → the compact result (action + a one-line reason).

Each stage is a small request with a strict output format (enum or compact
``key: value`` lines), and the decide stage can be pointed at a stronger model
than the others. The harness (``python -m decompose.run``) runs both options on
the labelled mail set and compares accuracy, calls, latency and cost.

Provider-agnostic over the project's ``LLMEngine`` seam: local Ollama by default,
OpenRouter with a flag — no OpenAI dependency.
"""
