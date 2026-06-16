"""
Long-Term Memory — reusable persistent knowledge as plain markdown files.

A global store (shared across all threads and tasks) under ~/.jarvis/memory/.
Files are intentionally simple, human-editable markdown. No embeddings, vector
search, or automatic extraction.

Two kinds of file:
  • Always-on (ALWAYS_ON) — injected into the system prompt on EVERY request,
    for all threads. These hold invariants for the whole agent:
      profile.md     — style, constraints, context (who the user is)
      invariants.md  — hard rules that must never change
  • On-demand — loaded into a session only when the user runs `memory load`:
      knowledge.md   — reusable notes and personal knowledge
      solutions.md   — reusable implementation patterns
"""

from pathlib import Path

_MEMORY_DIR = Path.home() / ".jarvis" / "memory"

# Files injected into every system prompt (in this order).
ALWAYS_ON: tuple[str, ...] = ("profile", "invariants")

# Section templates used by init() to scaffold the always-on files.
_TEMPLATES: dict[str, str] = {
    "profile": (
        "# Profile\n\n"
        "## Style\n"
        "- (brief or detailed? formal or conversational? code examples?)\n\n"
        "## Constraints\n"
        "- (stack, prohibitions, project rules, domain limits)\n\n"
        "## Context\n"
        "- (who you are, why you use the agent, what result you want)\n"
    ),
    "invariants": (
        "# Invariants\n\n"
        "Hard rules the agent must never violate, even if a request asks otherwise.\n\n"
        "- (e.g. Kotlin only; plan before code; free APIs only)\n"
    ),
}


class LongTermMemory:
    def __init__(self, directory: Path = _MEMORY_DIR) -> None:
        self._dir = directory

    @staticmethod
    def normalize(name: str) -> str:
        """Canonical memory name (without the .md suffix)."""
        return name[:-3] if name.endswith(".md") else name

    def list_files(self) -> list[str]:
        """Return the names (without .md) of all memory files, sorted."""
        if not self._dir.exists():
            return []
        return sorted(p.stem for p in self._dir.glob("*.md"))

    def read_always_on(self) -> dict[str, str]:
        """Return {name: content} for each always-on file that exists and is non-empty."""
        result: dict[str, str] = {}
        for name in ALWAYS_ON:
            content = self.read(name)
            if content and content.strip():
                result[name] = content
        return result

    def init_always_on(self) -> list[str]:
        """Scaffold any missing always-on files from templates. Returns created names."""
        created: list[str] = []
        for name in ALWAYS_ON:
            if not self.exists(name):
                self.write(name, _TEMPLATES[name])
                created.append(name)
        return created

    def path_for(self, name: str) -> Path:
        """Absolute path for a memory file (used by `memory edit` to open $EDITOR)."""
        return self._path(name)

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    def read(self, name: str) -> str | None:
        path = self._path(name)
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def write(self, name: str, content: str) -> None:
        """Create or overwrite a memory file."""
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(name).write_text(content, encoding="utf-8")

    def append(self, name: str, line: str) -> None:
        """Append a line to a memory file, creating it if absent."""
        existing = self.read(name) or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        self.write(name, existing + line + "\n")

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if path.exists():
            path.unlink()
            return True
        return False

    # ── Internal ───────────────────────────────────────────────────────────────

    def _path(self, name: str) -> Path:
        # Accept names with or without the .md suffix.
        stem = name[:-3] if name.endswith(".md") else name
        return self._dir / f"{stem}.md"
