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
    build_working_memory_block,
    build_prompt_generation_request,
    build_summary_prompt,
    build_facts_extraction_prompt,
    build_topic_routing_prompt,
    build_invariant_check_prompt,
    build_invariant_resolution_prompt,
    build_profile_style_prompt,
    _PROFILE_NO_CHANGE,
)
from .session.store import SessionStore
from .session.thread_store import ThreadStore
from .session.task_store import TaskStore
from .session.profile_store import ProfileStore
from .session.invariant_store import InvariantStore
from .session.behavior_log import BehaviorLog




# Compression strategy constants.
_COMPRESSION_INTERVAL: int = 5
_RECENT_TURNS: int = 5

# Default number of turns kept in the sliding-window context.
_DEFAULT_WINDOW_SIZE: int = 10

# API-call labels that count as the user-facing answer (for context-fill metric).
_ANSWER_LABELS: frozenset[str] = frozenset({"final_answer", "invariant_resolution"})

# Every N recorded interactions, remind the user they can refresh their style
# profile from recent behaviour (`personalize`). This is only a nudge — no LLM call.
_PROFILE_NUDGE_INTERVAL: int = 5

# How many of the most recent behaviour-log notes the personaliser learns from.
_PERSONALIZE_WINDOW: int = 100

# Opening instruction generated when the user advances into a stage (`task next`),
# so the new stage's work appears immediately without a separate user message.
_STAGE_ENTRY_PROMPTS: dict[str, str] = {
    "planning": "I'm ready to plan. Please produce the plan for this task.",
    "execution": "The plan is approved. Let's begin execution — present the first step.",
    "validation": "Execution is complete. Let's validate the result against the success criteria.",
    "done": "The task is finished. Please give a brief closing summary.",
}
# Opening instruction for `task back` (validation → execution).
_BACK_ENTRY_PROMPT: str = "Let's return to execution and keep working."


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
        self._tasks = TaskStore()
        self._profile = ProfileStore()
        self._invariants = InvariantStore()
        self._behavior = BehaviorLog()
        # Counts interactions this session to pace the personalisation nudge
        # (independent of the on-disk log, which is capped and would plateau).
        self._interactions: int = 0

        # Working-memory task linked to the active thread (None when unlinked).
        self._active_task: dict | None = None

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
        self._load_active_task()

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(self, user_input: str) -> str:
        """Send a message and return the assistant's response.

        Builds the full message list as [system] + history + [current turn],
        then appends both the user turn and assistant response to history.
        """
        params = self._config.runtime
        strategy = params.get("context_strategy", "none")
        api_calls: list[dict] = []
        generated_prompt: str | None = None

        # Personalisation + invariants go into every system prompt, alongside any
        # active task's stage instructions.
        profile = self._profile.read_active()
        invariants = self._invariants.read_active()
        system_prompt = build_system_prompt(
            params, self._active_task, profile, invariants
        )

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
            api_calls.append(_make_call_record(len(api_calls) + 1, "prompt_generation_stage1", stage1, self._client))
            final_user_message = generated_prompt
        else:
            final_user_message = build_strategy_prompt(params, user_input)

        # Topics strategy: classify the message into a topic before context assembly
        # so context can be scoped to the relevant topic's history.
        active_topic: str | None = None
        if strategy == "topics":
            active_topic, routing_record = self._route_to_topic(user_input)
            api_calls.append(routing_record)

        # system + working-memory block + context-strategy history + user turn.
        # The WM block (current task state) is injected ahead of history so it
        # survives compression and thread switches.
        wm_block = build_working_memory_block(self._active_task) if self._active_task else []
        messages = (
            [{"role": "system", "content": system_prompt}]
            + wm_block
            + self._build_context(active_topic)
            + [{"role": "user", "content": final_user_message}]
        )

        completion = self._client.complete(messages, params)
        response_text = completion.text.strip()
        api_calls.append(_make_call_record(len(api_calls) + 1, "final_answer", completion, self._client))

        # Invariant validation (the "requirements linter"): when invariants are
        # defined, check the reply in code and rework it once on a violation.
        invariant_notice: str | None = None
        if invariants:
            response_text, invariant_notice, completion = self._validate_invariants(
                invariants, messages, response_text, completion, params, api_calls
            )

        # Persist user/assistant turn; tag with topic when the topics strategy is active.
        user_msg: dict = {"role": "user", "content": user_input}
        asst_msg: dict = {"role": "assistant", "content": response_text}
        if active_topic:
            user_msg["topic"] = active_topic
            asst_msg["topic"] = active_topic
        self._history.append(user_msg)
        self._history.append(asst_msg)

        # Context-strategy background work (compression / facts / topic summaries).
        extra_notice, extra_record = self._run_background_strategy_work(active_topic)
        if extra_record:
            api_calls.append(extra_record)

        # Behaviour log (global, separate from chat threads): record this
        # interaction's shape so the profile refiner can learn style preferences.
        self._behavior.record(
            user_input=user_input,
            response_chars=len(response_text),
            solution_strategy=params.get("solution_strategy", "direct"),
            context_strategy=strategy,
            had_task=self._active_task is not None,
        )
        self._interactions += 1
        profile_notice = self._maybe_profile_nudge()

        # Accounting: every LLM call this turn is billed; the last answer-type
        # call reflects the shown response and its context-window fill.
        answer_calls = [c for c in api_calls if c["label"] in _ANSWER_LABELS]
        last_usage = (answer_calls or api_calls)[-1]["response"].get("usage") or {}
        # native_tokens_total is the model-side count after chat-template expansion;
        # falls back to total_tokens when the provider does not return native counts.
        native_ctx: int | None = last_usage.get("native_tokens_total") or last_usage.get("total_tokens") or None
        self._last_context_tokens = native_ctx or 0

        billing_tokens = sum((c["response"].get("usage") or {}).get("total_tokens") or 0 for c in api_calls)
        turn_cost = sum((c.get("cost") or {}).get("total_usd") or 0.0 for c in api_calls)
        self._thread_total_tokens += billing_tokens
        self._thread_total_cost += turn_cost
        turn_index = len(self._history) // 2
        # native_ctx stored as 4th element so the context chart can use persisted data.
        self._cost_series.append([turn_index, turn_cost, self._thread_total_cost, native_ctx])

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

        parts = [response_text]
        if invariant_notice:
            parts.append(invariant_notice)
        if extra_notice:
            parts.append(extra_notice)
        if profile_notice:
            parts.append(profile_notice)
        return "\n\n".join(parts)

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
        self._load_active_task()
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
        self._load_active_task()
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
                self._load_active_task()
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
                self._load_active_task()
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

    # ── Working memory (tasks) ─────────────────────────────────────────────────

    @property
    def active_task(self) -> dict | None:
        """The working-memory task linked to the active thread, or None."""
        return dict(self._active_task) if self._active_task else None

    def create_task(self, name: str | None = None) -> dict:
        """Create a task, link it to the active thread, and make it active."""
        task = self._tasks.new_task(name)
        task["thread_ids"] = [self._thread_id]
        self._tasks.save(task)
        self._threads.set_active_task(self._thread_id, task["id"])
        self._active_task = task
        return task

    def start_task(self, query: str) -> dict | None:
        """Link an existing task to the active thread and make it active."""
        task = self._tasks.find(query)
        if task is None:
            return None
        if self._thread_id not in task["thread_ids"]:
            task["thread_ids"].append(self._thread_id)
            self._tasks.save(task)
        self._threads.set_active_task(self._thread_id, task["id"])
        self._active_task = task
        return task

    def pause_task(self) -> str | None:
        """Unlink the active task from the thread (the task file is preserved)."""
        if self._active_task is None:
            return None
        name = self._active_task["name"]
        self._threads.set_active_task(self._thread_id, None)
        self._active_task = None
        return name

    def delete_task(self, query: str) -> str | None:
        """Delete a task file. Unlinks it from the active thread if it was active."""
        task = self._tasks.find(query)
        if task is None:
            return None
        self._tasks.delete(task["id"])
        if self._active_task and self._active_task["id"] == task["id"]:
            self._threads.set_active_task(self._thread_id, None)
            self._active_task = None
        return task["name"]

    def list_tasks(self) -> list[dict]:
        return self._tasks.list_all()

    def next_stage(self) -> tuple[str | None, str]:
        """Advance the active task to the next forward stage and continue.

        Deterministic, user-driven (`task next`). Records the leaving stage's
        result, advances in code (ALLOWED_TRANSITIONS enforced), then generates
        the new stage's opening reply. Returns (new_stage, reply_or_error).
        """
        return self._move_stage(None)

    def back_stage(self) -> tuple[str | None, str]:
        """Return a validation task to execution and continue (`task back`)."""
        return self._move_stage("execution")

    def _move_stage(self, target: str | None) -> tuple[str | None, str]:
        if self._active_task is None:
            return None, "No active task."
        current = self._active_task["stage"]
        # Record the leaving stage's result (last assistant message), and promote
        # the key results into the canonical task fields so they appear in
        # `task show` and carry to other threads — no extra LLM call needed.
        last_asst = next(
            (m["content"] for m in reversed(self._history) if m["role"] == "assistant"),
            None,
        )
        if last_asst:
            self._active_task.setdefault("stage_outputs", {})[current] = last_asst
            if current == "clarification" and not self._active_task.get("description"):
                self._active_task["description"] = last_asst
            elif current == "planning":
                self._active_task["plan"] = last_asst
        try:
            new_stage = self._tasks.advance_stage(self._active_task, target)
        except ValueError as exc:
            return None, f"Cannot move: {exc}."
        # Generate the new stage's opening reply in the same step (advance + continue).
        entry = _BACK_ENTRY_PROMPT if target == "execution" else _STAGE_ENTRY_PROMPTS.get(new_stage, "Continue.")
        reply = self.chat(entry)
        return new_stage, reply

    def add_completed(self, item: str) -> bool:
        """Record a completed item on the active task. Returns False if no task."""
        if self._active_task is None:
            return False
        self._active_task.setdefault("completed", []).append(item)
        # Drop a matching remaining item if present.
        self._active_task["remaining"] = [
            r for r in self._active_task.get("remaining", []) if r != item
        ]
        self._tasks.save(self._active_task)
        return True

    def add_remaining(self, item: str) -> bool:
        """Record a pending item on the active task. Returns False if no task."""
        if self._active_task is None:
            return False
        self._active_task.setdefault("remaining", []).append(item)
        self._tasks.save(self._active_task)
        return True

    # ── Invariants (single global hard-rule file) ───────────────────────────────

    def read_invariants(self) -> str | None:
        return self._invariants.read()

    def invariants_exist(self) -> bool:
        return self._invariants.exists()

    def init_invariants(self) -> bool:
        """Scaffold invariants.md from the template if missing. True if created."""
        return self._invariants.init()

    def invariants_path(self):
        """Filesystem path of invariants.md (for editing in $EDITOR)."""
        return self._invariants.path_for()

    # ── Profile (system-managed: onboarding + personalisation) ───────────────────

    def profile_exists(self) -> bool:
        return self._profile.exists()

    def read_profile(self) -> str | None:
        return self._profile.read()

    def onboard_profile(self, style: str, constraints: str, context: str) -> None:
        """Write profile.md from the onboarding interview answers."""
        self._profile.write_sections(style, constraints, context)

    def skip_onboarding(self) -> None:
        """Write a minimal default profile when the user skips the interview."""
        self._profile.write_default()

    def _maybe_profile_nudge(self) -> str | None:
        """Return a one-line reminder every N interactions (no LLM call).

        Only nudges when a profile with a Style section exists, since that is the
        only thing `personalize` can refine.
        """
        if self._profile.read_style() is None:
            return None
        if self._interactions > 0 and self._interactions % _PROFILE_NUDGE_INTERVAL == 0:
            return (
                "[Personalisation: enough recent activity to refresh your style profile — "
                "run 'personalize' to review a proposed update.]"
            )
        return None

    def propose_profile_style(self) -> tuple[str | None, str | None, str | None]:
        """Generate a proposed new Style section from recent behaviour.

        Learns from the most recent _PERSONALIZE_WINDOW behaviour-log notes.
        Returns (current_style, proposed_style, error). On success error is None;
        proposed_style is None when the model judges no change is warranted. Makes
        one LLM call; not billed to the thread (an out-of-conversation admin action).
        """
        current = self._profile.read_style()
        if current is None:
            return None, None, (
                "No profile.md with a '## Style' section. Run 'profile onboard' first."
            )
        recent = self._behavior.recent(_PERSONALIZE_WINDOW)
        if not recent:
            return current, None, "No recorded activity yet to learn from."

        prompt = build_profile_style_prompt(current, recent)
        params = {"model": self._config.runtime["model"]} if "model" in self._config.runtime else {}
        completion = self._client.complete([{"role": "user", "content": prompt}], params)
        proposed = completion.text.strip()
        if not proposed or proposed.upper().startswith(_PROFILE_NO_CHANGE):
            return current, None, None
        return current, proposed, None

    def apply_profile_style(self, new_style: str) -> bool:
        """Overwrite only the Style section of profile.md with new_style."""
        return self._profile.replace_style(new_style)

    def get_context_window(self, model_id: str) -> int | None:
        return self._client.get_context_window(model_id)

    @property
    def session(self) -> SessionStore:
        return self._session

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_active_task(self) -> None:
        """Load the working-memory task linked to the active thread, if any."""
        task_id = self._threads.get_active_task_id(self._thread_id)
        self._active_task = self._tasks.load(task_id) if task_id else None

    def _validate_invariants(
        self,
        invariants: str,
        messages: list[dict],
        response_text: str,
        completion: "Completion",
        params: dict,
        api_calls: list[dict],
    ) -> tuple[str, str | None, "Completion"]:
        """Check the reply against the invariants in code; resolve once on violation.

        On a violation the reply is regenerated to either (a) correct accidental
        drift while staying compliant, or (b) refuse the request and explain the
        conflict when it cannot be satisfied without breaking an invariant.

        Returns (final_text, notice_or_None, completion_for_finish_reason).
        """
        check_prompt = build_invariant_check_prompt(invariants, response_text)
        check_params = {"model": params["model"]} if "model" in params else {}
        check = self._client.complete([{"role": "user", "content": check_prompt}], check_params)
        api_calls.append(_make_call_record(len(api_calls) + 1, "invariant_check", check, self._client))

        if _invariants_ok(check.text):
            return response_text, None, completion

        resolution_prompt = build_invariant_resolution_prompt(
            invariants, response_text, check.text.strip()
        )
        resolution_messages = messages + [
            {"role": "assistant", "content": response_text},
            {"role": "user", "content": resolution_prompt},
        ]
        resolution = self._client.complete(resolution_messages, params)
        api_calls.append(_make_call_record(len(api_calls) + 1, "invariant_resolution", resolution, self._client))
        notice = (
            "[Invariant check: your request conflicted with the configured invariants — "
            "the reply above was adjusted or declined to respect them.]"
        )
        return resolution.text.strip(), notice, resolution

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


def _invariants_ok(verdict: str) -> bool:
    """True when the invariant checker reported no violations.

    The checker is told to answer exactly "OK" when compliant; anything else is
    treated as a violation list.
    """
    v = verdict.strip()
    if not v:
        return True
    return v.splitlines()[0].strip().upper().startswith("OK")


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
