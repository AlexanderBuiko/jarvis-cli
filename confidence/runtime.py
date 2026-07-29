"""Engine factory: pick cloud or local without the caller knowing which.

The confidence layer depends only on the ``LLMEngine`` Protocol, so this is the
one place that names a concrete client. Imports are function-local on purpose:
constructing ``OpenRouterClient`` loads the API key eagerly and raises when it is
missing, so merely importing this module must not require any key — the cost is
paid only when you actually ask for that engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.llm.engine import LLMEngine

# Cloud default matches the Day-6 baseline so numbers are comparable across days.
_OPENROUTER_DEFAULT_MODEL = "openai/gpt-4o-mini"


def build_engine(local: bool = False, model: str | None = None) -> tuple[LLMEngine, str]:
    """Return ``(engine, model_id)`` for local Ollama or cloud OpenRouter."""
    if local:
        from jarvis.ollama.client import DEFAULT_MODEL, OllamaClient
        return OllamaClient(), (model or DEFAULT_MODEL)
    from jarvis.openrouter.client import OpenRouterClient
    return OpenRouterClient(), (model or _OPENROUTER_DEFAULT_MODEL)
