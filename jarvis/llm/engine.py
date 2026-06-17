"""
LLMEngine — the abstraction the rest of the system depends on instead of a
concrete provider.

The tutor's architecture note is explicit: build from abstractions (LLM engine,
prompt builder, storages, invariant checker, response validator), then connect
specific providers (OpenAI, DeepSeek, GigaChat, OpenRouter, …) as implementations
of the interface. The agent, the orchestrator and every stage-agent talk to this
Protocol, never to a concrete HTTP client; tests supply a fake engine.

OpenRouterClient already satisfies this Protocol structurally, so no inheritance
is required — it is the production implementation.
"""

from typing import Any, Protocol, runtime_checkable

from ..openrouter.client import Completion


@runtime_checkable
class LLMEngine(Protocol):
    """The contract every LLM provider implementation must satisfy."""

    def complete(self, messages: list[dict], params: dict[str, Any]) -> Completion:
        """Send a chat-completion request and return the Completion."""
        ...

    def get_pricing(self, model_id: str) -> tuple[float | None, float | None]:
        """Return (input_$/M_tokens, output_$/M_tokens), or (None, None)."""
        ...

    def get_context_window(self, model_id: str) -> int | None:
        """Return the model's context window in tokens, or None if unknown."""
        ...
