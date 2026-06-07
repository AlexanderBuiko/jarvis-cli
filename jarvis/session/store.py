"""
In-memory session store.

Keeps a record of every completed interaction during the current REPL session.
Not persisted between launches — intentional, to allow clean-slate comparisons.
"""

import json
from dataclasses import dataclass, field
from typing import Any


def _fmt_ms(v: Any) -> str:
    if v is None:
        return "N/A"
    return f"{round(v)} ms"


def _fmt_tokens(v: Any) -> str:
    return "N/A" if v is None else str(v)


def _fmt_usd(v: Any) -> str:
    if v is None:
        return "N/A"
    return f"{v:.6f} USD"


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

    def format_results(self, mode: str = "default") -> str:
        """Format session results.

        mode:
          "default"   — human-readable view (no API payloads)
          "api"       — API request/response payloads only
          "benchmark" — API payloads + benchmark metrics table
        """
        if not self._entries:
            return "No interactions recorded in this session yet."

        sep = "─" * 60
        sections = []
        for entry in self._entries:
            if mode == "api":
                sections.append(self._fmt_api(entry, sep))
            elif mode == "benchmark":
                sections.append(self._fmt_benchmark(entry, sep))
            else:
                sections.append(self._fmt_default(entry, sep))

        return "\n".join(sections) + sep

    # ── Formatters ────────────────────────────────────────────────────────────

    def _fmt_default(self, entry: SessionEntry, sep: str) -> str:
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

        lines += ["", f"  Finish reason: {entry.finish_reason}", ""]
        return "\n".join(lines)

    def _fmt_api(self, entry: SessionEntry, sep: str) -> str:
        thin = "·" * 60
        lines = [
            sep,
            f"  Interaction #{entry.index}",
            sep,
            "",
        ]
        for call in entry.api_calls:
            lines += [
                f"  {thin}",
                f"  Call #{call['index']} — {call['label']}",
                "",
                "  Api Request:",
                "",
            ]
            for line in json.dumps(call["request"], indent=4).splitlines():
                lines.append(f"    {line}")
            lines += ["", "  Api Response:", ""]
            for line in json.dumps(call["response"], indent=4).splitlines():
                lines.append(f"    {line}")
            lines.append("")
        return "\n".join(lines)

    def _fmt_benchmark(self, entry: SessionEntry, sep: str) -> str:
        thin = "·" * 60
        lines = [
            sep,
            f"  Interaction #{entry.index}",
            sep,
            "",
            "  Question:",
            f"    {entry.original_request}",
            "",
        ]
        for call in entry.api_calls:
            bm = call.get("benchmark", {})
            lines += [
                f"  {thin}",
                f"  Call #{call['index']} — {call['label']}",
                "",
                "  Benchmark Info:",
                f"    Model             : {bm.get('actual_model') or 'N/A'}",
                f"    Latency           : {_fmt_ms(bm.get('latency_ms'))}",
                f"    Prompt Tokens     : {_fmt_tokens(bm.get('prompt_tokens'))}",
                f"    Completion Tokens : {_fmt_tokens(bm.get('completion_tokens'))}",
                f"    Total Tokens      : {_fmt_tokens(bm.get('total_tokens'))}",
                f"    Input Cost        : {_fmt_usd(bm.get('input_cost_usd'))}",
                f"    Output Cost       : {_fmt_usd(bm.get('output_cost_usd'))}",
                f"    Total Cost        : {_fmt_usd(bm.get('total_cost_usd'))}",
                f"    Finish Reason     : {bm.get('finish_reason') or 'N/A'}",
                "",
            ]
        return "\n".join(lines)
