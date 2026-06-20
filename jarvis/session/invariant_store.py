"""
Invariants — the single, app-wide set of hard rules the agent must never break.

There is exactly ONE invariants file for the whole application (global scope,
shared across every thread and task), stored separately from the dialogue under
~/.jarvis/memory/invariants.md. It is the only file the user authors by hand.

Invariants are the deliberate, durable decisions that do not change from request
to request: chosen architecture, agreed technical decisions, stack constraints,
business rules. They are injected into every system prompt AND enforced in code
(see JarvisAgent._validate_invariants), so a request that conflicts with them is
refused with an explanation rather than quietly honoured.
"""

from pathlib import Path

_FILENAME = "invariants.md"

_TEMPLATE = (
    "# Invariants\n\n"
    "Hard rules the agent must never violate, even if a request asks otherwise.\n"
    "These are global to the whole application.\n\n"
    "- (e.g. Kotlin only; plan before code; free APIs only; budget = $0)\n"
)


class InvariantStore:
    """Single global invariants.md file. No per-thread or per-task scope."""

    def __init__(self, directory: Path | None = None) -> None:
        # Resolve home at instantiation (not import) so $HOME-based test isolation works.
        self._path = (directory or (Path.home() / ".jarvis" / "memory")) / _FILENAME

    def read(self) -> str | None:
        """Return the invariants text, or None if the file is absent."""
        if not self._path.exists():
            return None
        try:
            return self._path.read_text(encoding="utf-8")
        except OSError:
            return None

    def read_active(self) -> str | None:
        """Return the invariants text only if present and non-empty, else None."""
        content = self.read()
        return content if content and content.strip() else None

    def exists(self) -> bool:
        return self._path.exists()

    def write(self, content: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(content, encoding="utf-8")

    def init(self) -> bool:
        """Scaffold invariants.md from the template if missing. Returns True if created."""
        if self._path.exists():
            return False
        self.write(_TEMPLATE)
        return True

    def path_for(self) -> Path:
        """Filesystem path of invariants.md (shown so the user can edit it directly)."""
        return self._path
