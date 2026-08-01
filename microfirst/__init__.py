"""Day-10 micro-model first — a cheap check before the big LLM.

Take a task where an LLM is the default reflex — here the Day-6 message-priority
classification — and put a **micro-model** in front of it. Most requests are easy
and never need a 7B generation; a tiny embedding classifier handles them, and only
the uncertain ones fall back to the big model.

Two tiers over the project's own seams:

* **Tier 1 — micro-model (mandatory).** An embedding nearest-centroid classifier
  built on the `Embedder` seam (`nomic-embed-text`, ~137M params, no text
  generation). It returns a structured label **and** a confidence status:
  `OK` when the nearest class is both close and clearly ahead, else `UNSURE`.
* **Tier 2 — LLM fallback.** The big model (`qwen2.5:7b`, or the Day-9 fine-tuned
  classifier) runs **only** when the micro-model says `UNSURE`.

The result is an inference pipeline where the micro-model absorbs most requests
before the big LLM is ever called. Run the harness with ``python -m microfirst.run``.
"""
