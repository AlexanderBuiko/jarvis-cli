"""
FakeEngine — an in-memory LLMEngine implementation for tests.

Demonstrates the value of the LLMEngine abstraction: the agent, the invariant
checker and the orchestrator can all be driven without any network access by
swapping in this fake. Responses are either a scripted queue (consumed in order)
or a callable that decides per call from the messages.
"""

from typing import Any, Callable

from jarvis.openrouter.client import Completion


class FakeEngine:
    def __init__(
        self,
        scripted: list[str] | None = None,
        responder: Callable[[list[dict], dict], str] | None = None,
    ) -> None:
        self.scripted = list(scripted or [])
        self.responder = responder
        self.calls: list[tuple[list[dict], dict]] = []

    def complete(self, messages: list[dict], params: dict[str, Any]) -> Completion:
        self.calls.append((messages, params))
        if self.responder is not None:
            text = self.responder(messages, params)
        elif self.scripted:
            text = self.scripted.pop(0)
        else:
            text = ""
        model = params.get("model", "test/model")
        return Completion(
            text=text,
            finish_reason="stop",
            request={"model": model, "messages": messages},
            response={
                "model": model,
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
            latency_ms=0.0,
        )

    def get_pricing(self, model_id: str) -> tuple[float | None, float | None]:
        return (None, None)

    def get_context_window(self, model_id: str) -> int | None:
        return None
