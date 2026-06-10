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

import re

try:
    import plotext as plt
    _PLOTEXT_AVAILABLE = True
except ImportError:
    _PLOTEXT_AVAILABLE = False

_ANSI = re.compile(r'\x1b\[[0-9;]*m')

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

    def get_cost_series(self) -> list[tuple[int, float, float]]:
        """Return per-turn cost data as [(turn_index, request_cost_usd, cumulative_cost_usd)]."""
        series = []
        cumulative = 0.0
        for entry in self._entries:
            for call in entry.api_calls:
                if call.get("label") == "final_answer":
                    cost = (call.get("cost") or {}).get("total_usd") or 0.0
                    cumulative += cost
                    turn = len(series) + 1
                    series.append((turn, cost, cumulative))
                    break
        return series

    def format_context_cost_table(self, context_window: int | None = None) -> str:
        """Per-turn context utilisation table for the current session.

        Columns: Turn | Prompt Tokens | Context % (when window known) | Request Cost
        Returns an empty string when there are no session entries.
        """
        rows = []
        for entry in self._entries:
            for call in entry.api_calls:
                if call.get("label") == "final_answer":
                    usage = call["response"].get("usage") or {}
                    # Prefer native_tokens_total (model-side, post-template) when available;
                    # fall back to total_tokens (OpenRouter estimate, pre-template).
                    ct = usage.get("native_tokens_total") or usage.get("total_tokens")
                    cost = (call.get("cost") or {}).get("total_usd")
                    rows.append((len(rows) + 1, ct, cost))
                    break

        if not rows:
            return ""

        if context_window:
            hdr = f"  {'Turn':>4}  {'Context Tokens':>15}  {'Context':>8}  {'Request Cost':>14}"
            div = f"  {'────':>4}  {'──────────────':>15}  {'───────':>8}  {'────────────':>14}"
        else:
            hdr = f"  {'Turn':>4}  {'Context Tokens':>15}  {'Request Cost':>14}"
            div = f"  {'────':>4}  {'──────────────':>15}  {'────────────':>14}"

        lines = [hdr, div]
        for turn, ct, cost in rows:
            tok_str = f"{ct:>14,}" if ct is not None else f"{'—':>14}"
            cost_str = f"${cost:>13.6f}" if cost is not None else f"  {'—':>13}"
            if context_window:
                pct_str = f"{round(ct * 100 / context_window):>6}%" if ct is not None else f"{'—':>7}"
                lines.append(f"  {turn:>4}  {tok_str}  {pct_str}  {cost_str}")
            else:
                lines.append(f"  {turn:>4}  {tok_str}  {cost_str}")

        lines.append("")
        return "\n".join(lines)

    def session_turn_count(self) -> int:
        """Number of final-answer turns recorded in this session."""
        return sum(
            1 for entry in self._entries
            for call in entry.api_calls
            if call.get("label") == "final_answer"
        )

    def get_context_series(
        self, context_window: int, turn_offset: int = 0
    ) -> list[tuple[int, float]]:
        """Return per-turn context fill as [(thread_turn_index, fill_pct)].

        turn_offset shifts the session-local index to match thread turn numbers
        when prior-session turns exist (e.g. offset=2 means session turn 1 → thread turn 3).
        """
        series = []
        for entry in self._entries:
            for call in entry.api_calls:
                if call.get("label") == "final_answer":
                    usage = (call["response"].get("usage") or {})
                    ct = usage.get("native_tokens_total") or usage.get("total_tokens")
                    if ct is not None:
                        pct = round(ct * 100 / context_window)
                        series.append((len(series) + 1 + turn_offset, pct))
                    break
        return series

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
                    *(
                        [
                            f"  native prompt:     {_fmt_int(usage.get('native_tokens_prompt'))}",
                            f"  native completion: {_fmt_int(usage.get('native_tokens_completion'))}",
                            f"  native total:      {_fmt_int(usage.get('native_tokens_total'))}",
                        ]
                        if any(usage.get(k) is not None for k in (
                            "native_tokens_prompt", "native_tokens_completion", "native_tokens_total"
                        ))
                        else []
                    ),
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


def _render_context_chart(series: list[tuple[int, float]]) -> str:
    """Render a line chart of context window fill % vs turn number.

    Returns an empty string when plotext is unavailable or fewer than 2 points exist.
    """
    if not _PLOTEXT_AVAILABLE or len(series) < 2:
        return ""

    turns = [s[0] for s in series]
    pcts = [s[1] for s in series]

    try:
        fig_w, fig_h = _chart_size()
        plt.clf()
        plt.plot(turns, pcts, color=(140, 140, 140))
        plt.title("Context Window Fill %")
        plt.xlabel("Turn")
        plt.ylabel("Fill %")
        plt.ylim(0, 100)
        plt.theme("clear")
        plt.plotsize(fig_w, fig_h)
        return plt.build()
    except Exception:
        return ""


def _chart_size() -> tuple[int, int]:
    """Return (width, height) for a full-width chart at 3:1 ratio."""
    from shutil import get_terminal_size
    tw = get_terminal_size((120, 24)).columns
    fig_w = min(tw, 160) // 2
    fig_h = max(5, fig_w // 3)
    return fig_w, fig_h


def _render_request_cost_chart(series: list) -> str:
    """Bar chart of per-turn request cost. Same size as all other charts."""
    if not _PLOTEXT_AVAILABLE or len(series) < 2:
        return ""
    turns = [s[0] for s in series]
    costs = [s[1] * 1000 for s in series]   # USD → m$
    try:
        fig_w, fig_h = _chart_size()
        plt.clf()
        plt.bar(turns, costs, color=(140, 140, 140), width=0.8)
        plt.title("Cost per request")
        plt.xlabel("Turn")
        plt.ylabel("m$ x10-3")
        plt.theme("clear")
        plt.plotsize(fig_w, fig_h)
        return plt.build()
    except Exception:
        return ""


def _render_cumulative_cost_chart(series: list) -> str:
    """Line chart of cumulative cost over turns. Same size as all other charts."""
    if not _PLOTEXT_AVAILABLE or len(series) < 2:
        return ""
    turns = [s[0] for s in series]
    cumulative = [s[2] * 1000 for s in series]   # USD → m$
    try:
        fig_w, fig_h = _chart_size()
        plt.clf()
        plt.plot(turns, cumulative, color=(140, 140, 140))
        plt.title("Cumulative cost")
        plt.xlabel("Turn")
        plt.ylabel("m$ x10-3")
        plt.theme("clear")
        plt.plotsize(fig_w, fig_h)
        return plt.build()
    except Exception:
        return ""
