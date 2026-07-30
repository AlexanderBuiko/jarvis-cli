"""Model escalation router — cheap model first, escalate to a stronger one on doubt.

A request-routing layer built over the project's ``LLMEngine`` seam. Every query
first hits a small, fast, cheap model. Two uncertainty heuristics read that
answer; when either says "not sure", the query is re-routed to a bigger, stronger
model and its answer is served instead. Confident answers stay on the cheap model,
so the fast path is the common path.

The two heuristics (the brief names both):

* **Confidence score** — the model self-rates 0..1 how sure it is. This is the
  primary signal: below a floor, escalate.
* **Response length / hedging** — a too-short answer or explicit hedge words
  ("I'm not sure", "it depends") corroborate uncertainty in the middle band, and
  contradict a high self-score when they appear together.

Provider-agnostic: the default pair is two *local* Ollama models (a small-parameter
model escalating to a bigger one, $0 and private), but the same code routes between
two OpenRouter models with a flag — no OpenAI dependency. Run the harness with
``python -m routing.run``.
"""
