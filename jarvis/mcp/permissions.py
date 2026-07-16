"""
Tool-permission gate — a human-in-the-loop guard on *mutating* MCP tool calls.

The agent's tool loop can call any tool the fleet exposes, including the ``files``
server's ``write_file``, which edits the developer's working tree. This policy decides
whether such a call may run *during the turn*, and queues the ones that need the user's
sign-off:

  • Read-only tools (list/read/search) and previews (``write_file(dry_run=True)``) are
    never gated — they can't change anything.
  • A real write runs in-turn when writes are pre-authorised (``auto`` — set from
    ``config set file_writes auto``) or already granted for this session ("allow always").
  • Otherwise the write is **not** performed now; it is recorded in ``pending`` and the
    model is told it's awaiting approval. The REPL drains ``pending`` after the turn
    (spinner stopped, on the main thread) and asks the user once / always / skip — the
    same idiom the task pipeline uses for its approval gates. This avoids prompting from
    the spinner's worker thread, which can't own the terminal.

The gate is injected into :class:`~jarvis.llm.gateway.LLMGateway` (CLI side only), so the
stdio server stays a dumb file worker and the server-side gateways (/help, /review,
/support) — which attach no gate — are unaffected.
"""

from __future__ import annotations

from typing import Any, Callable

# Tool basenames that mutate the working tree. The model may call them wire-named
# (``files__write_file``) or dotted (``files.write_file``); we match on the trailing
# basename so both route correctly.
DEFAULT_MUTATING = frozenset({"write_file", "delete_file"})


def _basename(tool_name: str) -> str:
    """The bare tool name, stripped of a wire (``a__b``) or dotted (``a.b``) server prefix."""
    return tool_name.replace("__", ".").rsplit(".", 1)[-1]


class ToolPermissions:
    """Decides whether a mutating tool call runs now; queues the rest for approval."""

    def __init__(
        self,
        *,
        mutating: frozenset[str] = DEFAULT_MUTATING,
        auto: bool | Callable[[], bool] = False,
    ) -> None:
        self._mutating = mutating
        # A bool, or a predicate read live each check — so `config set file_writes auto`
        # takes effect mid-session without rebuilding the gate.
        self._auto = auto
        self._granted: set[str] = set()  # basenames granted "always" this session
        self.pending: list[dict] = []    # writes awaiting the user's post-turn approval
        self.previews: list[dict] = []   # dry-run diffs to show the user in a read-only frame

    def _auto_on(self) -> bool:
        return bool(self._auto() if callable(self._auto) else self._auto)

    def _is_mutating(self, tool_name: str, args: dict[str, Any] | None) -> bool:
        """A tool counts as mutating only for a *real* write — a dry-run preview doesn't."""
        if _basename(tool_name) not in self._mutating:
            return False
        return not (args or {}).get("dry_run", False)

    def allow(self, tool_name: str, args: dict[str, Any] | None = None) -> bool:
        """True if the call may run now; otherwise queue it in ``pending`` and return False."""
        if not self._is_mutating(tool_name, args):
            return True
        if self._auto_on() or _basename(tool_name) in self._granted:
            return True
        self._enqueue(tool_name, args or {})
        return False

    def _enqueue(self, tool_name: str, args: dict[str, Any]) -> None:
        """Record a write for post-turn approval (deduped per file, latest wins)."""
        path = args.get("path")
        self.pending = [p for p in self.pending
                        if not (p["tool"] == tool_name and p["args"].get("path") == path)]
        self.pending.append({"tool": tool_name, "args": dict(args)})

    def take_pending(self) -> list[dict]:
        """Return and clear the queued writes (called by the REPL after the turn)."""
        items, self.pending = self.pending, []
        return items

    def grant_always(self, tool_name: str) -> None:
        """Grant a tool for the rest of the session (the user's 'allow always' choice)."""
        self._granted.add(_basename(tool_name))

    def add_preview(self, path: str, content: str) -> None:
        """Record a dry-run diff for the REPL to show in a read-only frame after the turn."""
        self.previews.append({"path": path, "content": content})

    def take_previews(self) -> list[dict]:
        """Return and clear the queued dry-run previews."""
        items, self.previews = self.previews, []
        return items
