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
    build_summary_prompt,
)
from .session.store import SessionStore
from .session.thread_store import ThreadStore


# Number of turns that trigger a compression cycle.
_COMPRESSION_INTERVAL: int = 5
# Number of most-recent turns always sent verbatim (never compressed).
_RECENT_TURNS: int = 5


class JarvisAgent:
    """
    Conversational agent that maintains history across turns.

    Each call to chat() appends the user turn and assistant response to the
    conversation history, which is included in every subsequent API request so
    the model retains full context of the dialogue.

    Conversation history is organized into named threads. On startup the most
    recently used thread is auto-resumed. New threads can be created and existing
    threads loaded via the history commands.
    """

    def __init__(self, client: OpenRouterClient, config_manager: ConfigManager) -> None:
        self._client = client
        self._config = config_manager
        self._threads = ThreadStore()
        self._threads.migrate_legacy()

        last = self._threads.load_last()
        if last:
            (
                self._thread_id, self._thread_name, self._history,
                self._thread_total_tokens, self._thread_total_cost, self._cost_series,
                self._summary, self._summary_covered_turns,
            ) = last
        else:
            self._thread_id, self._thread_name = self._threads.new_thread()
            self._history = []
            self._thread_total_tokens: int = 0
            self._thread_total_cost: float = 0.0
            self._cost_series: list = []
            self._summary: str | None = None
            self._summary_covered_turns: int = 0

        # Prompt tokens from the most recent API call — represents how much of
        # the context window is currently in use (system + full history + last user msg).
        self._last_context_tokens: int = 0

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

        # system + compressed-or-full history + current (strategy-processed) user turn.
        # History stores the original user text; strategy wrapping applies only
        # to the outgoing request and is not persisted in history.
        messages = (
            [{"role": "system", "content": system_prompt}]
            + self._build_context()
            + [{"role": "user", "content": final_user_message}]
        )

        completion = self._client.complete(messages, params)
        response_text = completion.text.strip()
        api_calls.append(_make_call_record(len(api_calls) + 1, "final_answer", completion, self._client))

        self._history.append({"role": "user", "content": user_input})
        self._history.append({"role": "assistant", "content": response_text})

        # Update cumulative token/cost counters from the final API call.
        final_call = api_calls[-1]
        usage = final_call["response"].get("usage") or {}

        # native_tokens_total is the model-side count after chat-template expansion;
        # it matches what the model's context-limit check uses and is more accurate
        # than total_tokens (OpenRouter's pre-template estimate).
        # Falls back to total_tokens when the provider does not return native counts.
        native_ctx: int | None = usage.get("native_tokens_total") or usage.get("total_tokens") or None
        self._last_context_tokens = native_ctx or 0

        # total_tokens (billing metric) is used for the cumulative billing counter.
        billing_tokens = usage.get("total_tokens") or 0
        turn_cost = (final_call.get("cost") or {}).get("total_usd") or 0.0
        self._thread_total_tokens += billing_tokens
        self._thread_total_cost += turn_cost
        turn_index = len(self._history) // 2
        # native_ctx stored as 4th element so the context chart can use persisted data.
        self._cost_series.append([turn_index, turn_cost, self._thread_total_cost, native_ctx])

        compression_notice, compression_record = self._maybe_compress()

        if compression_record:
            api_calls.append(compression_record)
            comp_tokens = (compression_record["response"].get("usage") or {}).get("total_tokens") or 0
            comp_cost = (compression_record.get("cost") or {}).get("total_usd") or 0.0
            self._thread_total_tokens += comp_tokens
            self._thread_total_cost += comp_cost
            # Roll compression cost into the triggering turn's cost_series entry so
            # charts reflect the full cost of operating that turn.
            if self._cost_series:
                self._cost_series[-1][1] += comp_cost
                self._cost_series[-1][2] = self._thread_total_cost

        self._threads.save(
            self._thread_id,
            self._thread_name,
            self._history,
            self._thread_total_tokens,
            self._thread_total_cost,
            self._cost_series,
            self._summary,
            self._summary_covered_turns,
        )

        self._session.add(
            user_input=user_input,
            config_snapshot=dict(params),
            response=response_text,
            finish_reason=completion.finish_reason,
            api_calls=api_calls,
            generated_prompt=generated_prompt,
        )

        if compression_notice:
            return f"{response_text}\n\n{compression_notice}"
        return response_text

    def reset_history(self) -> None:
        """Clear the active thread's messages (thread record is preserved)."""
        self._history.clear()
        self._thread_total_tokens = 0
        self._thread_total_cost = 0.0
        self._cost_series = []
        self._last_context_tokens = 0
        self._summary = None
        self._summary_covered_turns = 0
        self._threads.save(self._thread_id, self._thread_name, self._history)

    def new_thread(self, name: str | None = None) -> str:
        """Start a new empty thread. Returns the new thread name."""
        self._thread_id, self._thread_name = self._threads.new_thread(name)
        self._history = []
        self._thread_total_tokens = 0
        self._thread_total_cost = 0.0
        self._cost_series = []
        self._last_context_tokens = 0
        self._summary = None
        self._summary_covered_turns = 0
        return self._thread_name

    def load_thread(self, query: str) -> bool:
        """Switch to an existing thread by name or id prefix.

        Returns True on success, False if not found.
        """
        result = self._threads.load_by_name_or_id(query)
        if result is None:
            return False
        (
            self._thread_id, self._thread_name, self._history,
            self._thread_total_tokens, self._thread_total_cost, self._cost_series,
            self._summary, self._summary_covered_turns,
        ) = result
        self._last_context_tokens = 0  # unknown until the next API call in this session
        # Touch the file so it becomes the new "last used" thread.
        self._threads.save(self._thread_id, self._thread_name, self._history, self._thread_total_tokens, self._thread_total_cost, self._cost_series, self._summary, self._summary_covered_turns)
        return True

    def delete_thread(self, query: str) -> str:
        """Delete a thread by name or id prefix.

        If the active thread is deleted, auto-switch to the most recent remaining
        thread, or create a new one if none exist.

        Returns a human-readable result message.
        """
        result = self._threads.load_by_name_or_id(query)
        if result is None:
            return f"Thread not found: '{query}'."
        target_id, target_name, *_ = result
        self._threads.delete(target_id)

        if target_id == self._thread_id:
            last = self._threads.load_last()
            if last:
                (
                    self._thread_id, self._thread_name, self._history,
                    self._thread_total_tokens, self._thread_total_cost, self._cost_series,
                    self._summary, self._summary_covered_turns,
                ) = last
                self._threads.save(self._thread_id, self._thread_name, self._history, self._thread_total_tokens, self._thread_total_cost, self._cost_series, self._summary, self._summary_covered_turns)
                return (
                    f"Thread '{target_name}' deleted. "
                    f"Switched to '{self._thread_name}'."
                )
            else:
                self._thread_id, self._thread_name = self._threads.new_thread()
                self._history = []
                self._thread_total_tokens = 0
                self._thread_total_cost = 0.0
                self._cost_series = []
                self._last_context_tokens = 0
                self._summary = None
                self._summary_covered_turns = 0
                return (
                    f"Thread '{target_name}' deleted. "
                    f"Started new thread '{self._thread_name}'."
                )

        return f"Thread '{target_name}' deleted."

    def rename_thread(self, new_name: str) -> str:
        """Rename the active thread. Returns the new name."""
        self._thread_name = new_name
        self._threads.rename(self._thread_id, self._thread_name, self._history, self._thread_total_tokens, self._thread_total_cost, self._cost_series, self._summary, self._summary_covered_turns)
        return self._thread_name

    def list_threads(self) -> list[dict]:
        """Return all threads sorted by last-used time (newest first)."""
        return self._threads.list_all()

    @property
    def thread_name(self) -> str:
        return self._thread_name

    @property
    def thread_id(self) -> str:
        return self._thread_id

    @property
    def history(self) -> list[dict]:
        """A copy of the current conversation history (alternating user/assistant turns)."""
        return list(self._history)

    @property
    def last_context_tokens(self) -> int:
        """total_tokens from the most recent API call — current context window fill.

        Uses total_tokens (prompt + completion) because the current completion
        becomes part of the history sent on the next turn.
        """
        return self._last_context_tokens

    @property
    def thread_total_tokens(self) -> int:
        """Cumulative total tokens billed across all turns in this thread."""
        return self._thread_total_tokens

    @property
    def thread_total_cost(self) -> float:
        return self._thread_total_cost

    @property
    def cost_series(self) -> list:
        """Per-turn cost series: list of [turn_index, request_cost_usd, cumulative_cost_usd]."""
        return list(self._cost_series)

    @property
    def summary(self) -> str | None:
        """Current rolling summary text, or None if no compression has occurred."""
        return self._summary

    @property
    def summary_covered_turns(self) -> int:
        """Number of turns currently captured by the rolling summary."""
        return self._summary_covered_turns

    def get_context_window(self, model_id: str) -> int | None:
        return self._client.get_context_window(model_id)

    @property
    def session(self) -> SessionStore:
        return self._session

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_context(self) -> list[dict]:
        """Return the message list to include in the next API request.

        When a summary exists, replaces the covered portion of history with a
        synthetic exchange that presents the summary to the model, followed by
        the verbatim recent tail.
        """
        if self._summary is None or self._summary_covered_turns == 0:
            return self._history

        recent = self._history[self._summary_covered_turns * 2:]
        summary_block = [
            {
                "role": "user",
                "content": (
                    f"[Conversation summary — turns 1–{self._summary_covered_turns}]\n"
                    f"{self._summary}"
                ),
            },
            {
                "role": "assistant",
                "content": "Understood, I have the context from our earlier conversation.",
            },
        ]
        return summary_block + recent

    def _maybe_compress(self) -> tuple[str | None, dict | None]:
        """Trigger a rolling compression cycle if the threshold has been reached.

        Returns (notice_string, api_call_record) when compression ran, or (None, None).
        """
        total_turns = len(self._history) // 2
        if total_turns < _COMPRESSION_INTERVAL:
            return None, None
        if total_turns % _COMPRESSION_INTERVAL != 0:
            return None, None

        # How many turns should the summary cover after this cycle.
        turns_to_cover = total_turns - _RECENT_TURNS
        if turns_to_cover <= 0 or turns_to_cover <= self._summary_covered_turns:
            return None, None

        # The new chunk is only the turns not yet summarised.
        new_chunk = self._history[self._summary_covered_turns * 2: turns_to_cover * 2]
        if not new_chunk:
            return None, None

        summary_text, completion = self._generate_summary(new_chunk)
        self._summary = summary_text
        self._summary_covered_turns = turns_to_cover
        record = _make_call_record(0, "context_compression", completion, self._client)
        notice = (
            f"[Context compressed: turns 1–{turns_to_cover} summarised. "
            f"Turns {turns_to_cover + 1}–{total_turns} kept verbatim.]"
        )
        return notice, record

    def _generate_summary(self, new_chunk: list[dict]) -> tuple[str, "Completion"]:
        """Call the LLM to produce an updated rolling summary."""
        prompt = build_summary_prompt(self._summary, new_chunk)
        params: dict = {}
        if "model" in self._config.runtime:
            params["model"] = self._config.runtime["model"]
        completion = self._client.complete([{"role": "user", "content": prompt}], params)
        return completion.text.strip(), completion


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
