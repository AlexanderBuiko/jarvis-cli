"""
JarvisAgent — the central agent entity.

Owns conversation history and coordinates the full request/response pipeline.
The REPL and any other interface interact with Jarvis exclusively through this class.
"""

from .config.manager import ConfigManager
from .openrouter.client import DEFAULT_MODEL, OpenRouterClient, Completion
from .prompt_builder.builder import (
    build_system_prompt,
    build_strategy_prompt,
    build_prompt_generation_request,
)
from .session.store import SessionStore


class JarvisAgent:
    """
    Conversational agent that maintains history across turns.

    Each call to chat() appends the user turn and assistant response to the
    conversation history, which is included in every subsequent API request so
    the model retains full context of the dialogue.
    """

    def __init__(self, client: OpenRouterClient, config_manager: ConfigManager) -> None:
        self._client = client
        self._config = config_manager
        self._history: list[dict] = []
        self._session = SessionStore()

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(self, user_input: str) -> str:
        """Send a message and return the assistant's response.

        Builds the full message list as [system] + history + [current turn],
        then appends both the user turn and assistant response to history.
        """
        params = self._config.runtime
        system_prompt = build_system_prompt(params)
        api_calls: list[dict] = []
        generated_prompt: str | None = None

        if params.get("solution_strategy") == "prompt_generation":
            # Two-stage pipeline: stage 1 generates an optimised prompt for the
            # task; stage 2 sends that prompt as the actual user message.
            stage1_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": build_prompt_generation_request(user_input)},
            ]
            stage1_params = {"model": params["model"]} if "model" in params else {}
            stage1 = self._client.complete(stage1_messages, stage1_params)
            generated_prompt = stage1.text.strip()
            api_calls.append(_make_call_record(1, "prompt_generation_stage1", stage1, self._client))
            final_user_message = generated_prompt
        else:
            final_user_message = build_strategy_prompt(params, user_input)

        # system + full prior history + current (strategy-processed) user turn.
        # History stores the original user text; strategy wrapping applies only
        # to the outgoing request and is not persisted in history.
        messages = (
            [{"role": "system", "content": system_prompt}]
            + self._history
            + [{"role": "user", "content": final_user_message}]
        )

        completion = self._client.complete(messages, params)
        response_text = completion.text.strip()
        api_calls.append(_make_call_record(len(api_calls) + 1, "final_answer", completion, self._client))

        self._history.append({"role": "user", "content": user_input})
        self._history.append({"role": "assistant", "content": response_text})

        self._session.add(
            user_input=user_input,
            config_snapshot=dict(params),
            response=response_text,
            finish_reason=completion.finish_reason,
            api_calls=api_calls,
            generated_prompt=generated_prompt,
        )

        return response_text

    def reset_history(self) -> None:
        """Clear conversation history. The session log is not affected."""
        self._history.clear()

    @property
    def history(self) -> list[dict]:
        """A copy of the current conversation history (alternating user/assistant turns)."""
        return list(self._history)

    @property
    def session(self) -> SessionStore:
        return self._session


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_call_record(
    index: int,
    label: str,
    completion: Completion,
    client: "OpenRouterClient",
) -> dict:
    """Build a single API call record for the session log.

    Cost is computed here using the client's cached pricing data so that each
    record is self-contained. If pricing is unavailable all cost fields are None.
    """
    raw = completion.response
    usage = raw.get("usage") or {}

    # Pricing lookup uses the requested model ID (canonical, present in the
    # catalog). Falls back to the actual model reported in the response, which
    # may be a versioned variant (e.g. "qwen/qwen3-32b-04-28").
    requested_model: str = completion.request.get("model") or DEFAULT_MODEL
    actual_model: str = raw.get("model") or requested_model

    input_per_m, output_per_m = client.get_pricing(requested_model)
    if input_per_m is None and actual_model != requested_model:
        input_per_m, output_per_m = client.get_pricing(actual_model)

    prompt_tokens: int | None = usage.get("prompt_tokens")
    completion_tokens: int | None = usage.get("completion_tokens")

    input_cost: float | None = (
        (prompt_tokens / 1_000_000) * input_per_m
        if prompt_tokens is not None and input_per_m is not None
        else None
    )
    output_cost: float | None = (
        (completion_tokens / 1_000_000) * output_per_m
        if completion_tokens is not None and output_per_m is not None
        else None
    )
    total_cost: float | None = (
        input_cost + output_cost
        if input_cost is not None and output_cost is not None
        else None
    )

    return {
        "index": index,
        "label": label,
        "latency_ms": completion.latency_ms,
        "request": completion.request,
        "response": {
            "content": completion.text,
            "finish_reason": completion.finish_reason,
            "usage": usage or None,
            "model": actual_model,
            "id": raw.get("id"),
        },
        "cost": {
            "input_usd": input_cost,
            "output_usd": output_cost,
            "total_usd": total_cost,
        },
    }
