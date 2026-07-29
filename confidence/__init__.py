"""Day-7 confidence assessment and acceptance control for the classifier.

Wraps the Day-6 message-priority classifier with a layer that answers "should we
trust this answer?" without any fine-tuning. Two mechanisms combine into one
verdict — OK / UNSURE / FAIL:

* **Redundancy** (self-consistency): the same input is classified N times at a
  non-zero temperature; the labels are voted. Disagreement is uncertainty.
* **Scoring**: each run also returns a self-reported confidence; the mean
  confidence of the winning label, plus a format/allowed-value gate, decides
  whether a majority is trustworthy or must be rejected.

Provider-agnostic: it talks to the project's ``LLMEngine`` seam, so it runs on
OpenRouter (default) or a local Ollama model with a flag — no OpenAI dependency.
Run each step as ``python -m confidence.<step>``.
"""
