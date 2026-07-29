"""Day-6 fine-tuning tooling: build and validate a message-priority dataset.

Standalone assignment tooling, deliberately *outside* the ``jarvis`` package.
It talks to the OpenAI fine-tuning API directly, which is a separate seam from
the project's OpenRouter/Ollama engines, so nothing here imports ``jarvis`` and
nothing in ``jarvis`` imports this. Run each step as ``python -m finetune.<step>``.
"""
