"""
ConversationService — owns the active chat thread and its lifecycle.

All thread persistence and switching (create / load / rename / delete / reset)
lives here, operating on a single ThreadState. JarvisAgent holds one of these and
reads/writes ``service.state`` instead of juggling ten parallel attributes.
"""

from .state import ThreadState
from ..session.thread_store import ThreadStore


class ConversationService:
    def __init__(self, threads: ThreadStore | None = None) -> None:
        self._threads = threads or ThreadStore()
        self._threads.migrate_legacy()
        last = self._threads.load_last()
        if last:
            self._state = ThreadState.from_tuple(last)
        else:
            tid, tname = self._threads.new_thread()
            self._state = ThreadState(tid, tname)

    @property
    def state(self) -> ThreadState:
        return self._state

    def save(self) -> None:
        self._threads.save(*self._state.save_args())

    def reset(self) -> None:
        """Clear the active thread's contents (the thread record is preserved)."""
        self._state.clear()
        self._threads.save(self._state.id, self._state.name, self._state.history)

    def new_thread(self, name: str | None = None) -> str:
        """Start a new empty thread. Returns its name."""
        tid, tname = self._threads.new_thread(name)
        self._state = ThreadState(tid, tname)
        return tname

    def load_thread(self, query: str) -> bool:
        """Switch to an existing thread by name or id prefix. Returns success."""
        result = self._threads.load_by_name_or_id(query)
        if result is None:
            return False
        self._state = ThreadState.from_tuple(result)
        self.save()  # touch so it becomes the new "last used" thread
        return True

    def delete_thread(self, query: str) -> str:
        """Delete a thread by name or id prefix; auto-switch if it was active."""
        result = self._threads.load_by_name_or_id(query)
        if result is None:
            return f"Thread not found: '{query}'."
        target = ThreadState.from_tuple(result)
        self._threads.delete(target.id)

        if target.id != self._state.id:
            return f"Thread '{target.name}' deleted."

        last = self._threads.load_last()
        if last:
            self._state = ThreadState.from_tuple(last)
            self.save()
            return f"Thread '{target.name}' deleted. Switched to '{self._state.name}'."
        tid, tname = self._threads.new_thread()
        self._state = ThreadState(tid, tname)
        return f"Thread '{target.name}' deleted. Started new thread '{self._state.name}'."

    def rename_thread(self, new_name: str) -> str:
        self._state.name = new_name
        self._threads.rename(*self._state.save_args())
        return new_name

    def list_threads(self) -> list[dict]:
        return self._threads.list_all()

    # ── Attachments (finished task results pinned to this thread) ───────────────

    def attach(self, task_id: str, name: str, summary: str, content: str) -> None:
        """Pin a finished task's result to the active thread (replaces any prior
        attachment of the same task)."""
        self._state.attachments = [
            a for a in self._state.attachments if a.get("task_id") != task_id
        ]
        self._state.attachments.append(
            {"task_id": task_id, "name": name, "summary": summary, "content": content}
        )
        self.save()

    def detach(self, query: str) -> str | None:
        """Remove an attachment by task name or id prefix. Returns its name, or None."""
        removed = next(
            (
                a for a in self._state.attachments
                if a.get("name") == query or a.get("task_id", "").startswith(query)
            ),
            None,
        )
        if removed is None:
            return None
        self._state.attachments = [a for a in self._state.attachments if a is not removed]
        self.save()
        return removed.get("name")

    def attachments(self) -> list[dict]:
        return list(self._state.attachments)
