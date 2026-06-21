"""
LLMGateway — the single chokepoint for every LLM call in the application.

The KB's architecture note calls for one component through which all model access
flows, so cross-cutting concerns (accounting, and later retries / rate-limiting /
caching) live in exactly one place instead of being scattered across the agent,
the invariant checker and the stage agents. Every caller depends on this gateway,
never on a concrete engine.

It wraps an LLMEngine implementation and, on each call, optionally builds the
accounting record via make_call_record and appends it to a running ``api_calls``
list so the caller's billing stays correct. Background/admin calls that are billed
out of band can use ``record()`` to mint a record with an explicit index.
"""

from typing import Any

from .accounting import make_call_record
from .engine import LLMEngine
from ..openrouter.client import Completion


class LLMGateway:
    """The one place the rest of the system calls the model through."""

    def __init__(self, engine: LLMEngine) -> None:
        self._engine = engine

    def complete(
        self,
        messages: list[dict],
        params: dict[str, Any],
        *,
        label: str | None = None,
        api_calls: list[dict] | None = None,
    ) -> Completion:
        """Run a completion. When ``api_calls`` is given, append an accounting
        record (indexed sequentially) labelled ``label``."""
        completion = self._engine.complete(messages, params)
        if api_calls is not None:
            api_calls.append(
                make_call_record(len(api_calls) + 1, label or "completion", completion, self._engine)
            )
        return completion

    def record(self, index: int, label: str, completion: Completion) -> dict:
        """Mint an accounting record for a completion the caller bills separately."""
        return make_call_record(index, label, completion, self._engine)

    # ── Metadata pass-through (the gateway is the engine the app sees) ──────────

    def get_pricing(self, model_id: str) -> tuple[float | None, float | None]:
        return self._engine.get_pricing(model_id)

    def get_context_window(self, model_id: str) -> int | None:
        return self._engine.get_context_window(model_id)
