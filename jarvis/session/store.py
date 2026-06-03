"""
In-memory session store.

Keeps a record of every completed interaction during the current REPL session.
Not persisted between launches — intentional, to allow clean-slate comparisons.
"""

from dataclasses import dataclass, field
from ..config.schema import JarvisConfig


@dataclass
class SessionEntry:
    index: int
    original_request: str
    config_snapshot: dict        # copy of config at the time of the request
    final_response: str
    finish_reason: str | None = None
    generated_prompt: str | None = None
    clarifications: list[tuple[str, str]] = field(default_factory=list)


class SessionStore:
    def __init__(self):
        self._entries: list[SessionEntry] = []

    def add(
        self,
        original_request: str,
        cfg: JarvisConfig,
        final_response: str,
        finish_reason: str | None = None,
        generated_prompt: str | None = None,
        clarifications: list[tuple[str, str]] | None = None,
    ) -> None:
        entry = SessionEntry(
            index=len(self._entries) + 1,
            original_request=original_request,
            config_snapshot=cfg.to_dict(),
            final_response=final_response,
            finish_reason=finish_reason,
            generated_prompt=generated_prompt,
            clarifications=clarifications or [],
        )
        self._entries.append(entry)

    def format_results(self) -> str:
        if not self._entries:
            return "No interactions recorded in this session yet."

        sections = []
        sep = "─" * 60

        for entry in self._entries:
            lines = [
                sep,
                f"  Interaction #{entry.index}",
                sep,
                "",
                f"  Request : {entry.original_request}",
            ]

            if entry.clarifications:
                lines.append("")
                lines.append("  Clarifications:")
                for i, (q, a) in enumerate(entry.clarifications, start=1):
                    lines.append(f"    Q{i}: {q}")
                    lines.append(f"    A{i}: {a}")

            lines += [
                "",
                "  Configuration:",
            ]
            for k, v in entry.config_snapshot.items():
                lines.append(f"    {k} = {v}")

            if entry.generated_prompt is not None:
                lines += [
                    "",
                    "  Generated Prompt:",
                    "",
                ]
                for line in entry.generated_prompt.splitlines():
                    lines.append(f"    {line}")

            lines += [
                "",
                "  Response:",
                "",
            ]
            for line in entry.final_response.splitlines():
                lines.append(f"    {line}")

            lines += [
                "",
                f"  Finish reason: {entry.finish_reason}",
                "",
            ]

            sections.append("\n".join(lines))

        return "\n".join(sections) + "\n" + sep
