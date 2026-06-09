"""
In-memory session log.

Records every completed turn for the current session. Not persisted between
launches — each session starts clean.

Three views are available:
  format_chat()    — clean conversation transcript (primary view)
  format_summary() — per-model aggregates: tokens, cost, latency, call counts
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
        """Aggregate session statistics grouped by model.

        Shows conversation turn count, then a per-model block with token usage,
        cost, average latency, and API call count for each model used.
        """
        if not self._entries:
            return "No conversation recorded in this session yet."

        # ── Collect all calls grouped by model ────────────────────────────────
        # Preserves the order models were first seen.
        by_model: dict[str, list[dict]] = {}
        for entry in self._entries:
            for call in entry.api_calls:
                model = (
                    call["response"].get("model")
                    or entry.config_snapshot.get("model")
                    or DEFAULT_MODEL
                )
                by_model.setdefault(model, []).append(call)

        total_calls = sum(len(calls) for calls in by_model.values())

        lines = ["Session Summary", SEP, ""]

        lines += [
            "Conversation",
            f"  User messages:      {len(self._entries)}",
            f"  Assistant messages: {len(self._entries)}",
            f"  API calls:          {total_calls}",
            "",
        ]

        for model, calls in by_model.items():
            lines += [SEP, f"Model: {model}", SEP, ""]

            pt = _sum_field(calls, "prompt_tokens")
            ct = _sum_field(calls, "completion_tokens")
            tt = _sum_field(calls, "total_tokens")
            cost = _sum_cost(calls)
            avg_latency = _avg_latency(calls)

            lines += [
                f"  Prompt tokens:     {_fmt_int_grouped(pt)}",
                f"  Completion tokens: {_fmt_int_grouped(ct)}",
                f"  Total tokens:      {_fmt_int_grouped(tt)}",
                f"  Total cost:        {_fmt_usd(cost)}",
                f"  Avg latency:       {_fmt_latency(avg_latency)}",
                f"  API calls:         {len(calls)}",
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

                call_cost = call.get("cost") or {}
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
                    "Cost",
                    f"  input:  {_fmt_usd(call_cost.get('input_usd'))}",
                    f"  output: {_fmt_usd(call_cost.get('output_usd'))}",
                    f"  total:  {_fmt_usd(call_cost.get('total_usd'))}",
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


def _sum_field(calls: list[dict], token_field: str) -> int | None:
    """Sum a token field across a list of call records. Returns None if no data."""
    total = 0
    found = False
    for call in calls:
        v = (call["response"].get("usage") or {}).get(token_field)
        if v is not None:
            total += v
            found = True
    return total if found else None


def _sum_cost(calls: list[dict]) -> float | None:
    """Sum total_usd across a list of call records. Returns None if no data."""
    total = 0.0
    found = False
    for call in calls:
        v = (call.get("cost") or {}).get("total_usd")
        if v is not None:
            total += v
            found = True
    return total if found else None


def _avg_latency(calls: list[dict]) -> float | None:
    """Return the mean latency_ms across a list of call records."""
    values = [c["latency_ms"] for c in calls if c.get("latency_ms") is not None]
    return sum(values) / len(values) if values else None


def _fmt_int(v: Any) -> str:
    return "N/A" if v is None else str(v)


def _fmt_int_grouped(v: Any) -> str:
    """Format an integer with thousands separators."""
    return "N/A" if v is None else f"{v:,}"


def _fmt_usd(v: Any) -> str:
    return "N/A" if v is None else f"${v:.6f}"


def _fmt_ms(v: Any) -> str:
    return "N/A" if v is None else f"{round(v)} ms"


def _fmt_latency(v: Any) -> str:
    """Format latency in seconds with two decimal places."""
    return "N/A" if v is None else f"{v / 1000:.2f} s"
