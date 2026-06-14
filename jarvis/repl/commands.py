"""
REPL command handlers.

Each handler receives parsed arguments and shared application state, and
returns a string to print. No I/O is performed here.
"""

from ..agent import JarvisAgent, _COMPRESSION_INTERVAL
from ..config.manager import ConfigManager
from ..session.store import (
    SessionStore,
    _render_context_chart,
    _render_request_cost_chart,
    _render_cumulative_cost_chart,
)


HELP_TEXT = """
Jarvis — conversational AI agent

Modes
─────
  >   Prompt mode  — input is sent to the agent
  !   Command mode — input is dispatched to the REPL

  Type ! on an empty line to toggle between modes.
  Ctrl+G             Clear the input buffer
  ↑ / ↓             Navigate session history (prompt or command)
  ↑ / ↓             Navigate autocomplete suggestions when visible
  Tab                Accept selected suggestion

Commands
────────
  help                          Show this help message

  config show                   Show active configuration parameters
  config set <key> <val>        Set a parameter
  config update <k=v> …         Set multiple parameters at once
  config reset                  Clear all parameters (revert to API defaults)

  thread                        Show the current conversation context
  thread clear                  Clear the active thread's messages
  thread load                   List all saved threads
  thread load <name-or-id>      Switch to an existing thread
  thread new [name]             Start a new empty thread
  thread rename <name>          Rename the active thread
  thread delete <name-or-id>    Permanently delete a thread
  thread summary                Show token, cost, compression state, facts, and topic summaries

  session chat                  Show the full conversation transcript
  session summary               Show aggregate session statistics with cost charts
  session api                   Show raw API request/response payloads

  exit / quit                   Exit Jarvis

Parameters
──────────
  model              str    OpenRouter model identifier
  temperature        float  0.0 – 2.0   Sampling temperature
  top_p              float  0.0 – 1.0   Nucleus sampling probability
  top_k              int                Top-k sampling cutoff
  max_tokens         int                Maximum tokens in the response
  seed               int | none         Random seed for reproducibility

  solution_strategy  direct | step_by_step | prompt_generation | expert_panel
                             direct            — answer immediately (default)
                             step_by_step      — reason through steps explicitly
                             expert_panel      — three-expert panel with synthesis
                             prompt_generation — two-stage optimised prompt pipeline

  context_strategy   none | compression | sliding_window | sticky_facts | topics
                             none           — full history sent verbatim (default)
                             compression    — rolling summary replaces older turns
                             sliding_window — only the most recent N turns are sent
                             sticky_facts   — structured facts block prepended to history
                             topics         — automatic topic routing; context scoped per topic
                             Can only be changed on an empty thread.

  window_size        int    Number of turns kept when context_strategy=sliding_window (default: 10)
"""


def handle_help() -> str:
    return HELP_TEXT + "\n"


def handle_config_show(config_manager: ConfigManager) -> str:
    return config_manager.show()


def handle_config_set(args: list[str], config_manager: ConfigManager) -> str:
    if len(args) < 2:
        return "Usage: config set <key> <value>"
    key = args[0]
    value = " ".join(args[1:])
    try:
        return f"Updated: {config_manager.set(key, value)}"
    except (ValueError, TypeError) as exc:
        return f"Error: {exc}"


def handle_config_update(args: list[str], config_manager: ConfigManager) -> str:
    if not args:
        return "Usage: config update <key=value> [<key=value> ...]"
    try:
        return f"Updated:\n{config_manager.update(args)}"
    except (ValueError, TypeError) as exc:
        return f"Error: {exc}"


def handle_config_reset(config_manager: ConfigManager) -> str:
    config_manager.reset()
    return "Configuration cleared. Using API defaults.\n"


def handle_thread_show(agent: JarvisAgent) -> str:
    """Show what the agent currently holds as conversation context."""
    history = agent.history
    if not history:
        return "Conversation history is empty."
    turn_count = len(history) // 2
    tok = agent.thread_total_tokens
    cost = agent.thread_total_cost
    tok_str = f"{tok:,} tok" if tok else "0 tok"
    cost_str = f"  ${cost:.6f}" if cost else ""
    lines = [f"Conversation context ({turn_count} turn(s))  —  {tok_str}{cost_str}", ""]
    sep = "·" * 40
    turn = 0
    for i in range(0, len(history), 2):
        turn += 1
        user_entry = history[i]
        asst_entry = history[i + 1] if i + 1 < len(history) else {}
        topic = user_entry.get("topic")
        label = f"[{turn}, {topic}]" if topic else f"[{turn}]"
        lines += [
            sep,
            f"  {label} You   : {user_entry['content']}",
            f"  {label} Jarvis: {asst_entry.get('content', '(no response)')}",
        ]
    lines.append(sep)
    return "\n".join(lines)


def handle_thread_clear(agent: JarvisAgent) -> str:
    agent.reset_history()
    return "Conversation history cleared."


def handle_thread_load(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        threads = agent.list_threads()
        if not threads:
            return "No saved threads."
        sep = "─" * 60
        lines = [f"Saved threads ({len(threads)})", sep]
        for t in threads:
            active_marker = " ←" if t["id"] == agent.thread_id else ""
            tok = t.get("total_tokens") or 0
            cost = t.get("total_cost") or 0.0
            tok_str = f"{tok:>8,} tok" if tok else "       — tok"
            cost_str = f"  ${cost:.6f}" if cost else ""
            lines.append(
                f"  {t['name']:<20}  {t['id']}  {t['turns']:>3} turn(s)  {tok_str}{cost_str}{active_marker}"
            )
        lines.append(sep)
        lines.append("Use: thread load <name-or-id>")
        return "\n".join(lines)
    query = args[0]
    if agent.load_thread(query):
        return f"Loaded thread '{agent.thread_name}' ({agent.thread_id})  —  {len(agent.history) // 2} turn(s) restored."
    return f"Thread not found: '{query}'. Use 'thread load' to see available threads."


def handle_thread_new(args: list[str], agent: JarvisAgent) -> str:
    name = args[0] if args else None
    thread_name = agent.new_thread(name)
    return f"New thread started: '{thread_name}'."


def handle_thread_rename(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: thread rename <new-name>"
    new_name = args[0]
    agent.rename_thread(new_name)
    return f"Thread renamed to '{new_name}'.\n"


def handle_thread_delete(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: thread delete <name-or-id>"
    return agent.delete_thread(args[0])


def handle_thread_summary(
    agent: JarvisAgent,
    context_window: int | None = None,
) -> str:
    """Show token and cost statistics for the active thread, with cost charts."""
    tok = agent.thread_total_tokens
    cost = agent.thread_total_cost
    series = agent.cost_series
    turn_count = len(agent.history) // 2

    sep = "─" * 60
    lines = [
        "Thread Summary",
        sep,
        "",
        f"  Thread:       {agent.thread_name}  ({agent.thread_id})",
        f"  Turns:        {turn_count}",
        f"  Total tokens billed: {tok:,}" if tok else "  Total tokens billed: —",
        f"  Total cost:          ${cost:.6f}" if cost else "  Total cost:          —",
        "",
    ]

    # ── Section 1: Context Utilisation ───────────────────────────────────────
    if series and context_window:
        ctx_series = [
            (entry[0], round(entry[3] * 100 / context_window))
            for entry in series
            if len(entry) > 3 and entry[3] is not None
        ]
        if ctx_series:
            ctx_heading = f"Context Utilisation  (context window: {context_window:,} tok)"
            lines += [sep, ctx_heading, sep, ""]
            lines.append(f"  {'Turn':>4}  {'Context Tokens':>15}  {'Context':>8}")
            lines.append(f"  {'────':>4}  {'──────────────':>15}  {'───────':>8}")
            for entry in series:
                if len(entry) > 3 and entry[3] is not None:
                    pct_str = f"{round(entry[3] * 100 / context_window):>6}%"
                    lines.append(f"  {entry[0]:>4}  {entry[3]:>14,}  {pct_str}")
            lines.append("")
            ctx_chart = _render_context_chart(ctx_series)
            if ctx_chart:
                lines += [sep, ctx_chart]

    # ── Section 2: Cost per request ──────────────────────────────────────────
    if series:
        lines += [sep, "Cost per request", sep, ""]
        lines.append(f"  {'Turn':>4}  {'Request (USD)':>16}")
        lines.append(f"  {'────':>4}  {'─────────────':>16}")
        for entry in series:
            lines.append(f"  {entry[0]:>4}  ${entry[1]:>15.6f}")
        lines += [""]

        req_chart = _render_request_cost_chart(series)
        if req_chart:
            lines += [sep, req_chart]

    # ── Section 3: Cumulative cost ────────────────────────────────────────────
    if series:
        lines += [sep, "Cumulative cost", sep, ""]
        lines.append(f"  {'Turn':>4}  {'Cumulative (USD)':>18}")
        lines.append(f"  {'────':>4}  {'────────────────':>18}")
        for entry in series:
            lines.append(f"  {entry[0]:>4}  ${entry[2]:>17.6f}")
        lines += [""]

        cum_chart = _render_cumulative_cost_chart(series)
        if cum_chart:
            lines += [sep, cum_chart]

    # ── Section 4: Compression state ─────────────────────────────────────────
    summary = agent.summary
    if summary is not None:
        covered = agent.summary_covered_turns
        verbatim_start = covered + 1
        next_trigger = ((turn_count // _COMPRESSION_INTERVAL) + 1) * _COMPRESSION_INTERVAL
        lines += [
            sep, "Compression State", sep, "",
            f"  Summary covers:  turns 1–{covered}",
            f"  Verbatim tail:   turns {verbatim_start}–{turn_count}",
            f"  Next trigger:    turn {next_trigger}",
            "",
        ]
        for line in summary.splitlines():
            lines.append(f"  {line}" if line else "")
        lines += ["", sep]

    # ── Section 5: Sticky facts ───────────────────────────────────────────────
    facts = agent.facts
    if facts is not None:
        lines += [sep, "Sticky Facts", sep, ""]
        for line in facts.splitlines():
            lines.append(f"  {line}" if line else "")
        lines += ["", sep]

    # ── Section 6: Topic summaries ────────────────────────────────────────────
    topics = agent.topic_summaries
    if topics:
        lines += [sep, f"Topics ({len(topics)})", sep, ""]
        for topic_name, topic_summary in topics.items():
            topic_turns = sum(
                1 for m in agent.history
                if m.get("role") == "user" and m.get("topic") == topic_name
            )
            lines.append(f"  [{topic_name}]  {topic_turns} turn(s)")
            for line in topic_summary.splitlines():
                lines.append(f"    {line}" if line else "")
            lines.append("")
        lines.append(sep)

    return "\n".join(lines)


def handle_session_chat(session_store: SessionStore) -> str:
    return session_store.format_chat()


def handle_session_summary(session_store: SessionStore) -> str:
    return session_store.format_summary()


def handle_session_api(session_store: SessionStore) -> str:
    return session_store.format_api() + "\n"
