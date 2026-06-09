"""
In-memory session log.

Records every completed turn for the current session. Not persisted between
launches — each session starts clean.

Three views are available:
  format_chat()    — clean conversation transcript (primary view)
  format_summary() — aggregate statistics: message counts, tokens, model, config
  format_api()     — full API request/response payloads with per-call metrics
"""

import json
from dataclasses import dataclass, field
from typing import Any

from ..openrouter.client import DEFAULT_MODEL

SEP = "─" * 60


@dataclass
class SessionEntry:
    index: int
    user_input: str
    config_snapshot: dict[str, Any]
    response: str
    finish_reason: str | None = None
    api_calls: list[dict] = field(default_factory=list)
    generated_prompt: str | None = None


class SessionStore:
    def __init__(self) -> None:
        self._entries: list[SessionEntry] = []

    def add(
        self,
        user_input: str,
        config_snapshot: dict[str, Any],
        response: str,
        finish_reason: str | None = None,
        api_calls: list[dict] | None = None,
        generated_prompt: str | None = None,
    ) -> None:
        self._entries.append(SessionEntry(
            index=len(self._entries) + 1,
            user_input=user_input,
            config_snapshot=config_snapshot,
            response=response,
            finish_reason=finish_reason,
            api_calls=api_calls or [],
            generated_prompt=generated_prompt,
        ))

    # ── Public views ──────────────────────────────────────────────────────────

    def format_chat(self) -> str:
        """Clean conversation transcript — messages only, no metadata.

        Shows [User] and [Jarvis] blocks in order. Configuration changes
        between turns are shown inline as [Configuration Changed] events.
        """
        if not self._entries:
            return "No conversation recorded in this session yet."

        lines = ["Chat Session", SEP, ""]
        prev_config: dict[str, Any] = {}

        for entry in self._entries:
            changes = _config_diff(prev_config, entry.config_snapshot)
            if changes:
                lines += _fmt_config_change(changes)
            prev_config = entry.config_snapshot

            lines += ["[User]", ""]
            for line in entry.user_input.splitlines():
                lines.append(f"  {line}" if line else "")
            lines += ["", SEP, ""]

            lines += ["[Jarvis]", ""]
            for line in entry.response.splitlines():
                lines.append(f"  {line}" if line else "")
            lines += ["", SEP, ""]

        return "\n".join(lines)

    def format_summary(self) -> str:
        """Aggregate session statistics.

        Covers: message counts, model(s) used, active configuration,
        total token usage, and total API call count.
        """
        if not self._entries:
            return "No conversation recorded in this session yet."

        # ── Message counts ────────────────────────────────────────────────────
        turn_count = len(self._entries)

        # ── Models used ──────────────────────────────────────────────────────
        # Collect distinct model identifiers from API response fields,
        # preserving the order they first appeared.
        models: list[str] = []
        for entry in self._entries:
            for call in entry.api_calls:
                m = (
                    call["response"].get("model")
                    or entry.config_snapshot.get("model")
                    or DEFAULT_MODEL
                )
                if m not in models:
                    models.append(m)

        # ── Configuration ─────────────────────────────────────────────────────
        first_config = self._entries[0].config_snapshot
        last_config = self._entries[-1].config_snapshot
        config_changed = first_config != last_config

        # ── Token usage (null-safe sum across all API calls) ──────────────────
        pt = _aggregate(self._entries, "prompt_tokens")
        ct = _aggregate(self._entries, "completion_tokens")
        tt = _aggregate(self._entries, "total_tokens")

        # ── API call count ────────────────────────────────────────────────────
        total_calls = sum(len(e.api_calls) for e in self._entries)

        lines = ["Session Summary", SEP, ""]

        lines += [
            "Messages",
            f"  User:       {turn_count}",
            f"  Assistant:  {turn_count}",
            "",
        ]

        lines += ["Model"]
        for m in models:
            lines.append(f"  {m}")
        lines.append("")

        lines += ["Configuration"]
        if first_config:
            for k, v in first_config.items():
                lines.append(f"  {k} = {v}")
            if config_changed:
                lines.append("  (changed during session — see: session chat)")
        else:
            lines.append("  (none — API defaults)")
        lines.append("")

        lines += [
            "Usage",
            f"  Prompt tokens:     {_fmt_int(pt)}",
            f"  Completion tokens: {_fmt_int(ct)}",
            f"  Total tokens:      {_fmt_int(tt)}",
            "",
            "API Calls",
            f"  {total_calls}",
            "",
        ]

        return "\n".join(lines)

    def format_api(self) -> str:
        """Full API request/response payloads with per-call metrics.

        Calls are numbered globally across the entire session. Each call
        shows latency, token usage, finish reason, and the exact
        request/response JSON.
        """
        if not self._entries:
            return "No conversation recorded in this session yet."

        lines: list[str] = []
        global_call_num = 0

        for entry in self._entries:
            for call in entry.api_calls:
                global_call_num += 1
                resp = call["response"]
                usage = resp.get("usage") or {}
                model = (
                    resp.get("model")
                    or entry.config_snapshot.get("model")
                    or DEFAULT_MODEL
                )
                latency = call.get("latency_ms")

                lines += [
                    f"API Call #{global_call_num}  —  {call['label']}",
                    SEP,
                    "",
                    "Model",
                    f"  {model}",
                    "",
                    "Latency",
                    f"  {_fmt_ms(latency)}",
                    "",
                    "Tokens",
                    f"  prompt:     {_fmt_int(usage.get('prompt_tokens'))}",
                    f"  completion: {_fmt_int(usage.get('completion_tokens'))}",
                    f"  total:      {_fmt_int(usage.get('total_tokens'))}",
                    "",
                    f"Finish reason:  {resp.get('finish_reason') or 'N/A'}",
                    "",
                    "Request",
                    "",
                ]
                for line in json.dumps(call["request"], indent=2).splitlines():
                    lines.append(f"  {line}")
                lines += ["", "Response", ""]
                for line in json.dumps(resp, indent=2).splitlines():
                    lines.append(f"  {line}")
                lines += ["", SEP, ""]

        return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _config_diff(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, tuple[Any, Any]]:
    """Return {key: (old, new)} for every parameter that changed between turns."""
    changes: dict[str, tuple[Any, Any]] = {}
    for k in set(before) | set(after):
        old, new = before.get(k), after.get(k)
        if old != new:
            changes[k] = (old, new)
    return changes


def _fmt_config_change(changes: dict[str, tuple[Any, Any]]) -> list[str]:
    lines = ["[Configuration Changed]", ""]
    for key, (old, new) in sorted(changes.items()):
        old_str = str(old) if old is not None else "(default)"
        new_str = str(new) if new is not None else "(default)"
        lines += [f"  {key}:", f"    {old_str} → {new_str}", ""]
    lines += [SEP, ""]
    return lines


def _aggregate(entries: list[SessionEntry], token_field: str) -> int | None:
    """Sum a token field across all API calls. Returns None if no data is available."""
    total = 0
    found = False
    for entry in entries:
        for call in entry.api_calls:
            v = (call["response"].get("usage") or {}).get(token_field)
            if v is not None:
                total += v
                found = True
    return total if found else None


def _fmt_int(v: Any) -> str:
    return "N/A" if v is None else str(v)


def _fmt_ms(v: Any) -> str:
    return "N/A" if v is None else f"{round(v)} ms"
