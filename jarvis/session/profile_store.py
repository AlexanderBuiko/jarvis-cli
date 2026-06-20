"""
Profile — the system-managed personalisation file.

A single global profile.md under ~/.jarvis/memory/, stored separately from the
dialogue and injected into every system prompt. Unlike invariants (which the
user authors by hand), the profile is fully system-managed:

  • created by an onboarding interview the first time the agent runs, and
  • refined over time by the `personalize` command, which rewrites only the
    '## Style' section from the recent behaviour log.

The profile follows the KB's three groups: Style (how answers should look),
Constraints (soft project context), and Context (who the user is and why).
"""

import re
from pathlib import Path

_FILENAME = "profile.md"

# The only section the personaliser may rewrite. Constraints and Context are set
# during onboarding and left alone afterwards.
PROFILE_STYLE_HEADER = "## Style"

# Written when the user skips onboarding — a usable, empty-ish default.
_DEFAULT = (
    "# Profile\n\n"
    "## Style\n"
    "- (no preference recorded yet)\n\n"
    "## Constraints\n"
    "- (none recorded)\n\n"
    "## Context\n"
    "- (none recorded)\n"
)


class ProfileStore:
    def __init__(self, directory: Path | None = None) -> None:
        # Resolve home at instantiation (not import) so $HOME-based test isolation works.
        self._path = (directory or (Path.home() / ".jarvis" / "memory")) / _FILENAME

    def exists(self) -> bool:
        return self._path.exists()

    def read(self) -> str | None:
        if not self._path.exists():
            return None
        try:
            return self._path.read_text(encoding="utf-8")
        except OSError:
            return None

    def read_active(self) -> str | None:
        """Return the profile text only if present and non-empty, else None."""
        content = self.read()
        return content if content and content.strip() else None

    def write(self, content: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(content, encoding="utf-8")

    def write_default(self) -> None:
        """Write the minimal default profile (used when onboarding is skipped)."""
        self.write(_DEFAULT)

    def write_sections(self, style: str, constraints: str, context: str) -> None:
        """Assemble and write profile.md from the three onboarding answers."""
        content = (
            "# Profile\n\n"
            f"## Style\n{_as_bullets(style)}\n\n"
            f"## Constraints\n{_as_bullets(constraints)}\n\n"
            f"## Context\n{_as_bullets(context)}\n"
        )
        self.write(content)

    def read_style(self) -> str | None:
        """Return the body of the '## Style' section, or None if absent."""
        content = self.read()
        if content is None:
            return None
        return extract_section(content, PROFILE_STYLE_HEADER)

    def replace_style(self, new_body: str) -> bool:
        """Overwrite only the '## Style' section body, preserving the rest.

        Returns False if the profile or its Style section does not exist.
        """
        content = self.read()
        if content is None:
            return False
        updated = replace_section(content, PROFILE_STYLE_HEADER, new_body)
        if updated is None:
            return False
        self.write(updated)
        return True

    def path_for(self) -> Path:
        return self._path


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _as_bullets(answer: str) -> str:
    """Turn a free-text onboarding answer into a '- ' bullet line (or a default)."""
    answer = answer.strip()
    if not answer:
        return "- (none recorded)"
    return f"- {answer}"


# ── Markdown section helpers ────────────────────────────────────────────────────


def extract_section(text: str, header: str) -> str | None:
    """Return the body lines of a '## Header' section (excluding the header line).

    The section runs from the header up to the next '## ' heading or end of file.
    Returns None when the header is absent. The body is stripped of surrounding
    blank lines.
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
