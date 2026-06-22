"""
StageRunner — runs one stage turn against a task's own conversation.

Previously this logic lived on JarvisAgent (``run_stage_turn``) and was handed to
the Orchestrator as a bound-method callback, coupling the orchestrator to the God
object. It now has its own home: the Orchestrator depends on the StageRunner
*protocol*, and the concrete LLMStageRunner composes the shared abstractions
(gateway, prompt builder, memory coordinator, stores, invariant checker). Tests
supply a trivial fake runner, so the FSM can be exercised with no model access.

This is also the seam the (later) multi-agent work plugs into: a swarmed stage
can swap in a runner that fans a turn out to several reviewer agents and lets the
orchestrator consolidate — without the FSM or the rest of the app changing.
"""

from typing import Protocol

from ..llm.gateway import LLMGateway
from ..memory.coordinator import MemoryCoordinator
from ..prompt_builder.builder import build_system_prompt, build_working_memory_block
from .invariants import InvariantChecker


class StageRunner(Protocol):
    """Run one stage turn and return the raw assistant text (markers intact)."""

    def run(self, task: dict, entry_message: str, extra_system: str = "") -> str:
        ...


class LLMStageRunner:
    """Production StageRunner: build the prompt, call the model, validate, persist.

    A task is a standalone workspace: its turns read and append to the task's own
    message history (on the task file), never a chat thread. The durable task
    state rides in the working-memory block, and only a bounded window of the raw
    transcript is sent (via the MemoryCoordinator) so long tasks stay in budget.
    """

    def __init__(
        self,
        gateway: LLMGateway,
        config,
        memory: MemoryCoordinator,
        profile_store,
        invariant_store,
        invariant_checker: InvariantChecker,
        tasks,
    ) -> None:
        self._gateway = gateway
        self._config = config
        self._memory = memory
        self._profile = profile_store
        self._invariants = invariant_store
        self._invariant_checker = invariant_checker
        self._tasks = tasks

    def run(self, task: dict, entry_message: str, extra_system: str = "") -> str:
        params = self._config.runtime
        profile = self._profile.read_active()
        invariants = self._invariants.read_active()

        system_prompt = build_system_prompt(params, task, profile, invariants)
        if extra_system:
            system_prompt = f"{system_prompt}\n\n{extra_system}"

        history = task.setdefault("messages", [])
        messages = (
            [{"role": "system", "content": system_prompt}]
            + build_working_memory_block(task)
            + self._memory.build_task_context(history)
            + [{"role": "user", "content": entry_message}]
        )

        api_calls: list[dict] = []
        completion = self._gateway.complete(
            messages, params, label="stage_turn", api_calls=api_calls, use_tools=True
        )
        response_text = completion.text.strip()

        if invariants:
            response_text, _notice, completion = self._invariant_checker.validate(
                invariants, messages, response_text, completion, params, api_calls
            )

        # Every call this turn is billed to the task (requests / tokens / cost), so a
        # task pipeline reports its own spend (visible in `task show`) — previously
        # these records were discarded. The gateway already minted them.
        self._account(task, api_calls)

        history.append({"role": "user", "content": entry_message})
        history.append({"role": "assistant", "content": response_text})
        self._tasks.save(task)
        return response_text

    @staticmethod
    def _account(task: dict, api_calls: list[dict]) -> None:
        tokens = sum((c["response"].get("usage") or {}).get("total_tokens") or 0 for c in api_calls)
        cost = sum((c.get("cost") or {}).get("total_usd") or 0.0 for c in api_calls)
        task["api_call_count"] = task.get("api_call_count", 0) + len(api_calls)
        task["total_tokens"] = task.get("total_tokens", 0) + tokens
        task["total_cost"] = task.get("total_cost", 0.0) + cost
