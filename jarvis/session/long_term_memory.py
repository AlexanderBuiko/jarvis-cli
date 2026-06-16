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

import re
from pathlib import Path

_MEMORY_DIR = Path.home() / ".jarvis" / "memory"

# The profile section the refiner is allowed to rewrite. Constraints and Context
# are user-authored only — changing them would affect Jarvis's behaviour and
# overlap with the invariants, so the refiner never touches them.
PROFILE_STYLE_HEADER = "## Style"

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

    def read_profile_style(self) -> str | None:
        """Return the body of the profile's '## Style' section, or None if absent."""
        content = self.read("profile")
        if content is None:
            return None
        return extract_section(content, PROFILE_STYLE_HEADER)

    def replace_profile_style(self, new_body: str) -> bool:
        """Overwrite only the '## Style' section body of profile.md.

        Returns False if the profile or its Style section does not exist (the rest
        of the file — Constraints, Context — is left untouched).
        """
        content = self.read("profile")
        if content is None:
            return False
        updated = replace_section(content, PROFILE_STYLE_HEADER, new_body)
        if updated is None:
            return False
        self.write("profile", updated)
        return True

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


# ── Markdown section helpers ────────────────────────────────────────────────────


def extract_section(text: str, header: str) -> str | None:
    """Return the body lines of a '## Header' section (excluding the header line).

    The section runs from the header up to the next '## ' heading or end of file.
    Returns None when the header is absent. The returned body is stripped of
    surrounding blank lines.
    """
    lines = text.splitlines()
    start = _find_header(lines, header)
    if start is None:
        return None
    body: list[str] = []
    for line in lines[start + 1:]:
        if re.match(r"^#{1,2} ", line):
            break
        body.append(line)
    return "\n".join(body).strip()


def replace_section(text: str, header: str, new_body: str) -> str | None:
    """Replace a '## Header' section's body with new_body, preserving the rest.

    Returns the updated document, or None if the header is absent.
    """
    lines = text.splitlines()
    start = _find_header(lines, header)
    if start is None:
        return None
    # Find the end of the section (next heading or EOF).
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{1,2} ", lines[i]):
            end = i
            break
    rebuilt = lines[: start + 1] + [""] + new_body.strip().splitlines() + [""] + lines[end:]
    return "\n".join(rebuilt).rstrip() + "\n"


def _find_header(lines: list[str], header: str) -> int | None:
    target = header.strip().lower()
    for i, line in enumerate(lines):
        if line.strip().lower() == target:
            return i
    return None
