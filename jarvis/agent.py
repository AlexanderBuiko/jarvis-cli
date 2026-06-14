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
    build_facts_extraction_prompt,
    build_topic_routing_prompt,
)
from .session.store import SessionStore
from .session.thread_store import ThreadStore


# Compression strategy constants.
_COMPRESSION_INTERVAL: int = 5
_RECENT_TURNS: int = 5

# Default number of turns kept in the sliding-window context.
_DEFAULT_WINDOW_SIZE: int = 10


class JarvisAgent:
    """
    Conversational agent that maintains history across turns.

    Each call to chat() appends the user turn and assistant response to the
    conversation history, which is included in every subsequent API request so
    the model retains full context of the dialogue.

    Conversation history is organized into named threads. On startup the most
    recently used thread is auto-resumed. New threads can be created and existing
    threads loaded via the history commands.

    Context strategy (set via config context_strategy) controls how history is
    presented to the model. It may only be changed on an empty thread.

      none          — full history sent verbatim (default)
      compression   — rolling summary replaces older turns
      sliding_window — only the most recent N turns are sent
      sticky_facts  — a structured facts block is prepended to full history
      topics        — automatic topic routing; context is scoped to the active topic
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
                self._facts, self._topic_summaries,
            ) = last
        else:
            self._thread_id, self._thread_name = self._threads.new_thread()
            self._history = []
            self._thread_total_tokens: int = 0
            self._thread_total_cost: float = 0.0
            self._cost_series: list = []
            self._summary: str | None = None
            self._summary_covered_turns: int = 0
            self._facts: str | None = None
            self._topic_summaries: dict[str, str] = {}

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
        strategy = params.get("context_strategy", "none")
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

        # Topics strategy: classify the message into a topic before context assembly
        # so context can be scoped to the relevant topic's history.
        active_topic: str | None = None
        if strategy == "topics":
            active_topic, routing_record = self._route_to_topic(user_input)
            api_calls.append(routing_record)

        # system + context-strategy-assembled history + current (strategy-processed) user turn.
        # History stores the original user text; strategy wrapping applies only
        # to the outgoing request and is not persisted in history.
        messages = (
            [{"role": "system", "content": system_prompt}]
            + self._build_context(active_topic)
            + [{"role": "user", "content": final_user_message}]
        )

        completion = self._client.complete(messages, params)
        response_text = completion.text.strip()
        api_calls.append(_make_call_record(len(api_calls) + 1, "final_answer", completion, self._client))

        # Persist user/assistant turn; tag with topic when the topics strategy is active.
        user_msg: dict = {"role": "user", "content": user_input}
        asst_msg: dict = {"role": "assistant", "content": response_text}
        if active_topic:
            user_msg["topic"] = active_topic
            asst_msg["topic"] = active_topic
        self._history.append(user_msg)
        self._history.append(asst_msg)

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

        # Account for the topics routing pre-call (runs before the main call in api_calls).
        if strategy == "topics":
            routing_call = api_calls[0] if api_calls[0]["label"] == "topic_routing" else None
            if routing_call:
                r_tokens = (routing_call["response"].get("usage") or {}).get("total_tokens") or 0
                r_cost = (routing_call.get("cost") or {}).get("total_usd") or 0.0
                self._thread_total_tokens += r_tokens
                self._thread_total_cost += r_cost
                if self._cost_series:
                    self._cost_series[-1][1] += r_cost
                    self._cost_series[-1][2] = self._thread_total_cost

        # Run context-strategy background work and account for any extra API calls.
        extra_notice, extra_record = self._run_background_strategy_work(active_topic)

        if extra_record:
            api_calls.append(extra_record)
            extra_tokens = (extra_record["response"].get("usage") or {}).get("total_tokens") or 0
            extra_cost = (extra_record.get("cost") or {}).get("total_usd") or 0.0
            self._thread_total_tokens += extra_tokens
            self._thread_total_cost += extra_cost
            # Roll background cost into the triggering turn's cost_series entry so
            # charts reflect the full cost of operating that turn.
            if self._cost_series:
                self._cost_series[-1][1] += extra_cost
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
            self._facts,
            self._topic_summaries,
        )

        self._session.add(
            user_input=user_input,
            config_snapshot=dict(params),
            response=response_text,
            finish_reason=completion.finish_reason,
            api_calls=api_calls,
            generated_prompt=generated_prompt,
        )

        if extra_notice:
            return f"{response_text}\n\n{extra_notice}"
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
        self._facts = None
        self._topic_summaries = {}
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
        self._facts = None
        self._topic_summaries = {}
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
            self._facts, self._topic_summaries,
        ) = result
        self._last_context_tokens = 0  # unknown until the next API call in this session
        # Touch the file so it becomes the new "last used" thread.
        self._threads.save(
            self._thread_id, self._thread_name, self._history,
            self._thread_total_tokens, self._thread_total_cost, self._cost_series,
            self._summary, self._summary_covered_turns,
            self._facts, self._topic_summaries,
        )
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
                    self._facts, self._topic_summaries,
                ) = last
                self._threads.save(
                    self._thread_id, self._thread_name, self._history,
                    self._thread_total_tokens, self._thread_total_cost, self._cost_series,
                    self._summary, self._summary_covered_turns,
                    self._facts, self._topic_summaries,
                )
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
                self._facts = None
                self._topic_summaries = {}
                return (
                    f"Thread '{target_name}' deleted. "
                    f"Started new thread '{self._thread_name}'."
                )

        return f"Thread '{target_name}' deleted."

    def rename_thread(self, new_name: str) -> str:
        """Rename the active thread. Returns the new name."""
        self._thread_name = new_name
        self._threads.rename(
            self._thread_id, self._thread_name, self._history,
            self._thread_total_tokens, self._thread_total_cost, self._cost_series,
            self._summary, self._summary_covered_turns,
            self._facts, self._topic_summaries,
        )
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

    @property
    def facts(self) -> str | None:
        """Current sticky facts text, or None if no facts have been extracted."""
        return self._facts

    @property
    def topic_summaries(self) -> dict[str, str]:
        """Current per-topic summaries dict. Empty if the topics strategy has not run."""
        return dict(self._topic_summaries)

    def get_context_window(self, model_id: str) -> int | None:
        return self._client.get_context_window(model_id)

    @property
    def session(self) -> SessionStore:
        return self._session

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_context(self, active_topic: str | None = None) -> list[dict]:
        """Return the message list to include in the next API request.

        Dispatches to the appropriate assembly method based on the active
        context strategy. Defaults to full history when no strategy is set.
        """
        strategy = self._config.runtime.get("context_strategy", "none")
        if strategy == "compression":
            return self._build_compressed_context()
        if strategy == "sliding_window":
            return self._build_windowed_context()
        if strategy == "sticky_facts":
            return self._build_facts_context()
        if strategy == "topics":
            return self._build_topic_context(active_topic)
        return list(self._history)

    def _build_compressed_context(self) -> list[dict]:
        """Return history with older turns replaced by a rolling summary block."""
        if self._summary is None or self._summary_covered_turns == 0:
            return list(self._history)

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

    def _build_windowed_context(self) -> list[dict]:
        """Return only the most recent N turns of history."""
        window = self._config.runtime.get("window_size", _DEFAULT_WINDOW_SIZE)
        return self._history[max(0, len(self._history) - window * 2):]

    def _build_facts_context(self) -> list[dict]:
        """Return full history prefixed with a structured facts block."""
        if not self._facts:
            return list(self._history)
        facts_block = [
            {
                "role": "user",
                "content": f"[Conversation facts]\n{self._facts}",
            },
            {
                "role": "assistant",
                "content": "Understood, I have noted these facts.",
            },
        ]
        return facts_block + self._history

    def _build_topic_context(self, active_topic: str | None) -> list[dict]:
        """Return only the messages belonging to the active topic, with its summary block."""
        if not active_topic:
            return list(self._history)

        topic_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in self._history
            if m.get("topic") == active_topic
        ]

        existing_summary = self._topic_summaries.get(active_topic)
        if not existing_summary:
            return topic_messages

        summary_block = [
            {
                "role": "user",
                "content": f"[Topic summary — {active_topic}]\n{existing_summary}",
            },
            {
                "role": "assistant",
                "content": "Understood, I have the context from our earlier discussion on this topic.",
            },
        ]
        return summary_block + topic_messages

    def _run_background_strategy_work(
        self, active_topic: str | None = None
    ) -> tuple[str | None, dict | None]:
        """Run any post-turn background work required by the active context strategy.

        Returns (notice_string, api_call_record) when a background call was made,
        or (None, None) when no background work is needed.
        """
        strategy = self._config.runtime.get("context_strategy", "none")
        if strategy == "compression":
            return self._maybe_compress()
        if strategy == "sticky_facts":
            record = self._update_facts()
            return None, record
        if strategy == "topics" and active_topic:
            record = self._update_topic_summary(active_topic)
            return None, record
        return None, None

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

        summary_text, completion = self._generate_summary(self._summary, new_chunk)
        self._summary = summary_text
        self._summary_covered_turns = turns_to_cover
        record = _make_call_record(0, "context_compression", completion, self._client)
        notice = (
            f"[Context compressed: turns 1–{turns_to_cover} summarised. "
            f"Turns {turns_to_cover + 1}–{total_turns} kept verbatim.]"
        )
        return notice, record

    def _generate_summary(
        self, existing_summary: str | None, new_chunk: list[dict]
    ) -> tuple[str, "Completion"]:
        """Call the LLM to produce an updated rolling summary."""
        prompt = build_summary_prompt(existing_summary, new_chunk)
        params: dict = {}
        if "model" in self._config.runtime:
            params["model"] = self._config.runtime["model"]
        completion = self._client.complete([{"role": "user", "content": prompt}], params)
        return completion.text.strip(), completion

    def _update_facts(self) -> dict | None:
        """Call the LLM to update the sticky facts after each turn."""
        latest_exchange = self._history[-2:]
        prompt = build_facts_extraction_prompt(self._facts, latest_exchange)
        params: dict = {}
        if "model" in self._config.runtime:
            params["model"] = self._config.runtime["model"]
        completion = self._client.complete([{"role": "user", "content": prompt}], params)
        self._facts = completion.text.strip()
        return _make_call_record(0, "facts_extraction", completion, self._client)

    def _route_to_topic(self, user_input: str) -> tuple[str, dict]:
        """Call the LLM to determine which topic this message belongs to.

        Returns (topic_name, call_record). Creates a new topic name when no
        existing topic matches.
        """
        prompt = build_topic_routing_prompt(user_input, self._topic_summaries)
        params: dict = {}
        if "model" in self._config.runtime:
            params["model"] = self._config.runtime["model"]
        completion = self._client.complete([{"role": "user", "content": prompt}], params)
        topic = completion.text.strip().lower().replace(" ", "-")
        record = _make_call_record(0, "topic_routing", completion, self._client)
        return topic, record

    def _update_topic_summary(self, topic: str) -> dict | None:
        """Eagerly update the summary for the given topic after each turn."""
        latest_exchange = [m for m in self._history[-2:] if m.get("topic") == topic]
        if not latest_exchange:
            return None
        existing_summary = self._topic_summaries.get(topic)
        summary_text, completion = self._generate_summary(existing_summary, latest_exchange)
        self._topic_summaries[topic] = summary_text
        return _make_call_record(0, "topic_summary_update", completion, self._client)


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
