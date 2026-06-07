"""
In-memory session store.

Keeps a record of every completed interaction during the current REPL session.
Not persisted between launches — intentional, to allow clean-slate comparisons.
"""

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionEntry:
    index: int
    original_request: str
    config_snapshot: dict[str, Any]    # mode runtime params at request time
    final_response: str
    finish_reason: str | None = None
    # Full ordered trace of every OpenRouter call made for this interaction.
    # Each element is one call record (see _make_call_record in loop.py).
    api_calls: list[dict] = field(default_factory=list)
    generated_prompt: str | None = None
    clarifications: list[tuple[str, str]] = field(default_factory=list)


class SessionStore:
    def __init__(self) -> None:
        self._entries: list[SessionEntry] = []

    def add(
        self,
        original_request: str,
        config_snapshot: dict[str, Any],
        final_response: str,
        finish_reason: str | None = None,
        api_calls: list[dict] | None = None,
        generated_prompt: str | None = None,
        clarifications: list[tuple[str, str]] | None = None,
    ) -> None:
        entry = SessionEntry(
            index=len(self._entries) + 1,
            original_request=original_request,
            config_snapshot=config_snapshot,
            final_response=final_response,
            finish_reason=finish_reason,
            api_calls=api_calls or [],
            generated_prompt=generated_prompt,
            clarifications=clarifications or [],
        )
        self._entries.append(entry)

    def format_results(self) -> str:
        if not self._entries:
            return "No interactions recorded in this session yet."

        sections = []
        sep = "─" * 60
        thin = "·" * 60

        for entry in self._entries:
            # ── Human-readable view ────────────────────────────────────────
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
                    lines.append(f"    Clarification round {i}:")
                    lines.append(f"      Q: {q}")
                    lines.append(f"      A: {a}")

            lines += ["", "  Configuration:"]
            if entry.config_snapshot:
                for k, v in entry.config_snapshot.items():
                    lines.append(f"    {k} = {v}")
            else:
                lines.append("    (none — basic mode)")

            if entry.generated_prompt is not None:
                lines += ["", "  Generated Prompt:", ""]
                for line in entry.generated_prompt.splitlines():
                    lines.append(f"    {line}")

            lines += ["", "  Response:", ""]
            for line in entry.final_response.splitlines():
                lines.append(f"    {line}")

            lines += ["", f"  Finish reason: {entry.finish_reason}"]

            # ── Technical JSON view (all OpenRouter calls) ─────────────────
            lines += ["", f"  {thin}", "  OpenRouter Call Trace:", ""]

            trace = {
                "interaction_id": entry.index,
                "requests": entry.api_calls,
            }
            trace_json = json.dumps(trace, indent=4)
            for line in trace_json.splitlines():
                lines.append(f"    {line}")

            lines.append("")
            sections.append("\n".join(lines))

        return "\n".join(sections) + sep
