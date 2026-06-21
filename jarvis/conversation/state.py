"""
ThreadState — the in-memory representation of one conversation thread.

Replaces the 10-field tuple that JarvisAgent unpacked in four separate places
(every unpack a chance to desync). The field order matches ThreadStore's tuple
contract so conversion is mechanical.
"""

from dataclasses import dataclass, field


@dataclass
class ThreadState:
    id: str
    name: str
    history: list[dict] = field(default_factory=list)
    total_tokens: int = 0
    total_cost: float = 0.0
    cost_series: list = field(default_factory=list)
    summary: str | None = None
    summary_covered_turns: int = 0
    facts: str | None = None
    topic_summaries: dict[str, str] = field(default_factory=dict)
    # Finished task results pinned to this thread as reference context. Each:
    # {task_id, name, summary, content}.
    attachments: list[dict] = field(default_factory=list)

    @classmethod
    def from_tuple(cls, t: tuple) -> "ThreadState":
        """Build from ThreadStore's load tuple (field order is identical)."""
        return cls(*t)

    def save_args(self) -> tuple:
        """The positional arguments ThreadStore.save/rename expect."""
        return (
            self.id, self.name, self.history, self.total_tokens, self.total_cost,
            self.cost_series, self.summary, self.summary_covered_turns,
            self.facts, self.topic_summaries, self.attachments,
        )

    def clear(self) -> None:
        """Reset the thread's contents (keeps id/name)."""
        self.history = []
        self.total_tokens = 0
        self.total_cost = 0.0
        self.cost_series = []
        self.summary = None
        self.summary_covered_turns = 0
        self.facts = None
        self.topic_summaries = {}
        self.attachments = []
