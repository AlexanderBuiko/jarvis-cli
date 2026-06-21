"""
MemoryCoordinator — owns context assembly and the background memory strategies.

The KB's working-memory model says context must be layered and *selected* per
turn ("the anti-pattern is to include everything saved in every prompt"). This
component is the single home for that logic, lifted out of JarvisAgent:

  • chat context assembly per context_strategy (none / compression /
    sliding_window / sticky_facts / topics);
  • the post-turn background work each strategy needs (rolling compression,
    sticky-facts extraction, topic routing + per-topic summaries);
  • task context assembly — bounded so a long-running task's transcript cannot
    grow without limit (the durable task state already rides in the
    working-memory block, so only a recent window of raw turns is needed).

It is deliberately *stateless*: callers own the per-thread strategy state
(summary, facts, topic summaries) and pass it in; the coordinator returns the
assembled context or the updated state plus an accounting record. All model
calls go through the injected LLMGateway.
"""

from dataclasses import dataclass

from ..config.manager import ConfigManager
from ..llm.gateway import LLMGateway
from ..prompt_builder.builder import (
    build_summary_prompt,
    build_facts_extraction_prompt,
    build_topic_routing_prompt,
)

# Compression strategy constants (moved here from JarvisAgent).
COMPRESSION_INTERVAL: int = 5
RECENT_TURNS: int = 5

# Default number of turns kept in the sliding-window context (chat and tasks).
DEFAULT_WINDOW_SIZE: int = 10


@dataclass
class CompressionResult:
    summary: str
    summary_covered_turns: int
    notice: str
    record: dict


@dataclass
class BackgroundResult:
    """Updated strategy state after a turn's background work (only set fields change)."""
    summary: str | None = None
    summary_covered_turns: int | None = None
    facts: str | None = None
    topic_summary: tuple[str, str] | None = None  # (topic, summary)
    notice: str | None = None
    record: dict | None = None


class MemoryCoordinator:
    def __init__(self, gateway: LLMGateway, config: ConfigManager) -> None:
        self._gateway = gateway
        self._config = config

    @property
    def strategy(self) -> str:
        return self._config.runtime.get("context_strategy", "none")

    # ── Chat context assembly ──────────────────────────────────────────────────

    def build_chat_context(
        self,
        history: list[dict],
        *,
        active_topic: str | None = None,
        summary: str | None = None,
        summary_covered_turns: int = 0,
        facts: str | None = None,
        topic_summaries: dict[str, str] | None = None,
    ) -> list[dict]:
        """Assemble the chat context for the next request per the active strategy."""
        topic_summaries = topic_summaries or {}
        strategy = self.strategy
        if strategy == "compression":
            return self._compressed(history, summary, summary_covered_turns)
        if strategy == "sliding_window":
            return self._windowed(history)
        if strategy == "sticky_facts":
            return self._facts_context(history, facts)
        if strategy == "topics":
            return self._topic_context(history, active_topic, topic_summaries)
        return list(history)

    def build_task_context(self, task_messages: list[dict]) -> list[dict]:
        """Bounded task transcript: only the most recent window of turns.

        The durable task state (plan, current step, preceding-stage output) is
        injected separately as the working-memory block, so older raw turns are
        redundant and would otherwise grow context without limit.
        """
        window = self._config.runtime.get("window_size", DEFAULT_WINDOW_SIZE)
        return task_messages[max(0, len(task_messages) - window * 2):]

    def _compressed(self, history, summary, summary_covered_turns) -> list[dict]:
        if summary is None or summary_covered_turns == 0:
            return list(history)
        recent = history[summary_covered_turns * 2:]
        summary_block = [
            {
                "role": "user",
                "content": (
                    f"[Conversation summary — turns 1–{summary_covered_turns}]\n{summary}"
                ),
            },
            {
                "role": "assistant",
                "content": "Understood, I have the context from our earlier conversation.",
            },
        ]
        return summary_block + recent

    def _windowed(self, history) -> list[dict]:
        window = self._config.runtime.get("window_size", DEFAULT_WINDOW_SIZE)
        return history[max(0, len(history) - window * 2):]

    def _facts_context(self, history, facts) -> list[dict]:
        if not facts:
            return list(history)
        facts_block = [
            {"role": "user", "content": f"[Conversation facts]\n{facts}"},
            {"role": "assistant", "content": "Understood, I have noted these facts."},
        ]
        return facts_block + history

    def _topic_context(self, history, active_topic, topic_summaries) -> list[dict]:
        if not active_topic:
            return list(history)
        topic_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in history
            if m.get("topic") == active_topic
        ]
        existing_summary = topic_summaries.get(active_topic)
        if not existing_summary:
            return topic_messages
        summary_block = [
            {"role": "user", "content": f"[Topic summary — {active_topic}]\n{existing_summary}"},
            {
                "role": "assistant",
                "content": "Understood, I have the context from our earlier discussion on this topic.",
            },
        ]
        return summary_block + topic_messages

    # ── Topic routing (runs before context assembly) ───────────────────────────

    def route_topic(self, user_input: str, topic_summaries: dict[str, str]) -> tuple[str, dict]:
        """Classify a message into a topic. Returns (topic_name, call_record)."""
        prompt = build_topic_routing_prompt(user_input, topic_summaries)
        completion = self._gateway.complete([{"role": "user", "content": prompt}], self._bg_params())
        topic = completion.text.strip().lower().replace(" ", "-")
        return topic, self._gateway.record(0, "topic_routing", completion)

    # ── Post-turn background work ──────────────────────────────────────────────

    def run_background(
        self,
        *,
        history: list[dict],
        active_topic: str | None,
        summary: str | None,
        summary_covered_turns: int,
        facts: str | None,
        topic_summaries: dict[str, str],
    ) -> BackgroundResult:
        """Run the background work the active strategy requires after a turn."""
        strategy = self.strategy
        if strategy == "compression":
            comp = self._maybe_compress(history, summary, summary_covered_turns)
            if comp is None:
                return BackgroundResult()
            return BackgroundResult(
                summary=comp.summary,
                summary_covered_turns=comp.summary_covered_turns,
                notice=comp.notice,
                record=comp.record,
            )
        if strategy == "sticky_facts":
            new_facts, record = self._update_facts(history, facts)
            return BackgroundResult(facts=new_facts, record=record)
        if strategy == "topics" and active_topic:
            updated = self._update_topic_summary(history, active_topic, topic_summaries)
            if updated is None:
                return BackgroundResult()
            new_summary, record = updated
            return BackgroundResult(topic_summary=(active_topic, new_summary), record=record)
        return BackgroundResult()

    def _maybe_compress(self, history, summary, summary_covered_turns) -> CompressionResult | None:
        total_turns = len(history) // 2
        if total_turns < COMPRESSION_INTERVAL or total_turns % COMPRESSION_INTERVAL != 0:
            return None
        turns_to_cover = total_turns - RECENT_TURNS
        if turns_to_cover <= 0 or turns_to_cover <= summary_covered_turns:
            return None
        new_chunk = history[summary_covered_turns * 2: turns_to_cover * 2]
        if not new_chunk:
            return None
        summary_text, completion = self._generate_summary(summary, new_chunk)
        record = self._gateway.record(0, "context_compression", completion)
        notice = (
            f"[Context compressed: turns 1–{turns_to_cover} summarised. "
            f"Turns {turns_to_cover + 1}–{total_turns} kept verbatim.]"
        )
        return CompressionResult(summary_text, turns_to_cover, notice, record)

    def _update_facts(self, history, facts) -> tuple[str, dict]:
        latest_exchange = history[-2:]
        prompt = build_facts_extraction_prompt(facts, latest_exchange)
        completion = self._gateway.complete([{"role": "user", "content": prompt}], self._bg_params())
        return completion.text.strip(), self._gateway.record(0, "facts_extraction", completion)

    def _update_topic_summary(self, history, topic, topic_summaries) -> tuple[str, dict] | None:
        latest_exchange = [m for m in history[-2:] if m.get("topic") == topic]
        if not latest_exchange:
            return None
        existing_summary = topic_summaries.get(topic)
        summary_text, completion = self._generate_summary(existing_summary, latest_exchange)
        return summary_text, self._gateway.record(0, "topic_summary_update", completion)

    def _generate_summary(self, existing_summary, new_chunk):
        prompt = build_summary_prompt(existing_summary, new_chunk)
        completion = self._gateway.complete([{"role": "user", "content": prompt}], self._bg_params())
        return completion.text.strip(), completion

    def _bg_params(self) -> dict:
        """Background calls pin only the model, mirroring the prior behaviour."""
        return {"model": self._config.runtime["model"]} if "model" in self._config.runtime else {}
