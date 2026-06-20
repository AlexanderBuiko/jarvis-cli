"""
REPL command handlers.

Each handler receives parsed arguments and shared application state, and
returns a string to print. Handlers are pure except `personalize`, which
prompts for confirmation before applying a profile update.
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

  task                          Show the active task (working memory)
  task new [name]               Create a task workspace and enter it
  task list                     List all saved tasks and their stages
  task start <name-or-id>       Enter an existing task workspace
  task run                      Continue the entered task with no new input
  task exit                     Leave the task, back to chat (state preserved)
  task delete <name-or-id>      Permanently delete a task

  Tasks and chat are two separate surfaces. Threads ('thread …') are pure
  conversation. A task is a standalone workspace with its own context: 'task start'
  (or 'task new') enters it, 'task exit' leaves. While inside a task your messages
  drive its pipeline; outside, they're normal chat.

  Stages: clarification → planning → execution → validation → done (enforced in code).
  Inside a task your next message drives it, and 'task run' continues with no new
  input. The pipeline pauses only when it needs you:
    • a free-text question (clarification, or an execution step needing input), or
    • a Confirm / Reject choice at the two critical gates — plan approval and the
      final done decision (↑/↓ to move the arrow, Enter to choose). Reject asks
      "What's the problem?" and reworks with your feedback.
  Execution runs step-by-step under a live step table; press Ctrl+C to stop (the
  last completed step is saved — 'task run' resumes from it). At done, a short
  summary is shown and the full deliverable is saved to a result file (its path is
  shown and also in 'task show').

  invariants                    Show the global invariants (hard rules)
  invariants init               Scaffold invariants.md from a template

  profile                       Show the system-managed user profile
  profile onboard               Run (or re-run) the onboarding interview

  invariants.md is the single, app-wide hard-rule file. Scaffold it with
  'invariants init', then edit ~/.jarvis/memory/invariants.md directly.
  It is injected into every prompt AND enforced in code: when a request conflicts
  with an invariant, the agent refuses, names the invariant, and explains why.

  profile.md is system-managed: created by 'profile onboard' and refined by
  'personalize'. It is injected into every prompt (all threads).

  personalize                   Propose a profile.md Style update from recent activity
                                (shows current vs proposed, asks before overwriting).
                                Only the '## Style' section is ever changed.

  exit / quit                   Exit Jarvis

Parameters
──────────
  model              str    OpenRouter model identifier
                            Can only be changed on an empty thread.
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
    tok_str = f"{tok:,} tokens" if tok else "0 tokens"
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
            tok_str = f"{tok:>8,} tokens" if tok else "       — tokens"
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
            ctx_heading = f"Context Utilisation  (context window: {context_window:,} tokens)"
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


# ── Working memory (tasks) ──────────────────────────────────────────────────


def render_plan_progress(task: dict) -> str | None:
    """Render the plan as a step table with per-step status, or None if no steps.

    ✓ completed   ▶ in-progress   ○ pending. The status glyph is the first
    non-space character on each row, which the live input-panel uses to colour it.
    """
    steps = task.get("plan_steps") or []
    if not steps:
        return None
    idx = task.get("step_index", 0)
    done = min(idx, len(steps))
    lines = [f"Steps ({done}/{len(steps)} done)"]
    width = len(str(len(steps)))
    for i, step in enumerate(steps):
        glyph = "✓" if i < idx else ("▶" if i == idx else "○")
        lines.append(f"  {glyph}  {str(i + 1).rjust(width)}. {step}")
    return "\n".join(lines)


def _format_task(task: dict) -> str:
    sep = "─" * 60
    lines = [
        "Task (Working Memory)",
        sep,
        f"  Name:    {task.get('name', '')}",
        f"  Id:      {task.get('id', '')}",
        f"  Stage:   {task.get('stage', '')}",
    ]
    if task.get("current_step"):
        lines.append(f"  Step:    {task['current_step']}")
    if task.get("expected_action"):
        lines.append(f"  Next:    {task['expected_action']}")

    # Progress checklist (plan steps with status). The plan itself lives in the
    # stage results below, so we don't repeat it here.
    progress = render_plan_progress(task)
    if progress:
        lines += [""]
        lines += [f"  {ln}" for ln in progress.splitlines()]

    if task.get("notes"):
        lines += ["", f"  Notes:   {task['notes']}"]

    # Stage results are the single source for each stage's output (clarification
    # understanding, the plan, the per-step execution log, validation findings).
    # Goal and Plan are intentionally not shown separately — they live here.
    outputs = task.get("stage_outputs") or {}
    ordered = [s for s in ("clarification", "planning", "execution", "validation") if s in outputs]
    if ordered:
        lines += ["", "  Stage results:"]
        for stage in ordered:
            lines.append(f"    [{stage}]")
            lines += [f"      {ln}" for ln in outputs[stage].splitlines()]
    if task.get("result_path"):
        lines += ["", f"  Result file: {task['result_path']}"]
    lines.append(sep)
    return "\n".join(lines)


def handle_task_show(agent: JarvisAgent) -> str:
    task = agent.active_task
    if task is None:
        return "No active task. Use 'task new <name>' or 'task start <name-or-id>'."
    return _format_task(task)


def handle_task_new(args: list[str], agent: JarvisAgent) -> str:
    name = " ".join(args) if args else None
    task = agent.create_task(name)
    return (
        f"Task created: '{task['name']}' ({task['id']}). "
        f"Describe what you want to accomplish to begin (your next message starts it)."
    )


def handle_task_list(agent: JarvisAgent) -> str:
    tasks = agent.list_tasks()
    if not tasks:
        return "No saved tasks. Use 'task new <name>'."
    active = agent.active_task
    active_id = active["id"] if active else None
    sep = "─" * 60
    lines = [f"Tasks ({len(tasks)})", sep]
    for t in tasks:
        marker = " ←" if t["id"] == active_id else ""
        lines.append(f"  {t['name']:<28}  {t['id']}  {t['stage']:<14}{marker}")
    lines.append(sep)
    lines.append("Use: task start <name-or-id>")
    return "\n".join(lines)


def handle_task_start(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: task start <name-or-id>"
    task = agent.start_task(" ".join(args))
    if task is None:
        return f"Task not found: '{' '.join(args)}'. Use 'task list'."
    return (
        f"Entered task '{task['name']}' (stage: {task['stage']}). "
        f"Type a message to continue, or 'task run'. 'task exit' to leave."
    )


def handle_task_exit(agent: JarvisAgent) -> str:
    name = agent.exit_task()
    if name is None:
        return "Not in a task — you're already in chat mode."
    return f"Left task '{name}' (state preserved). Back in chat mode; 'task start {name}' to resume."


def handle_task_delete(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: task delete <name-or-id>"
    name = agent.delete_task(" ".join(args))
    if name is None:
        return f"Task not found: '{' '.join(args)}'."
    return f"Task '{name}' deleted."


# ── Invariants (single global hard-rule file) ────────────────────────────────


def handle_invariants_show(agent: JarvisAgent) -> str:
    content = agent.read_invariants()
    if content is None or not content.strip():
        return "No invariants set. Use 'invariants init' to scaffold, then edit the file."
    sep = "─" * 60
    return (
        f"Invariants (global hard rules)\n{sep}\n{content.rstrip()}\n{sep}\n"
        f"Edit directly: {agent.invariants_path()}"
    )


def handle_invariants_init(agent: JarvisAgent) -> str:
    path = agent.invariants_path()
    if not agent.init_invariants():
        return f"invariants.md already exists. Edit it directly:\n  {path}"
    return f"Scaffolded invariants.md. Edit it directly:\n  {path}"


# ── Profile (system-managed) ──────────────────────────────────────────────────


def handle_profile_show(agent: JarvisAgent) -> str:
    content = agent.read_profile()
    if content is None or not content.strip():
        return "No profile yet. Run 'profile onboard' to create one."
    sep = "─" * 60
    return f"Profile (system-managed)\n{sep}\n{content.rstrip()}\n{sep}"


_ONBOARD_QUESTIONS = [
    (
        "style",
        "1/3  Style — how should answers look? "
        "(e.g. brief or detailed, formal or conversational, code examples?)\n> ",
    ),
    (
        "constraints",
        "2/3  Constraints — any project context worth knowing? "
        "(e.g. preferred stack, domain, working conditions)\n> ",
    ),
    (
        "context",
        "3/3  Context — who are you and what do you want from the agent?\n> ",
    ),
]


def run_onboarding(agent: JarvisAgent, *, forced: bool = False) -> str:
    """Interactive onboarding interview that creates profile.md.

    Skippable: typing 'skip' (or submitting nothing at the first question) writes
    a minimal default profile. Re-runnable any time via `profile onboard`.
    Returns a status line to print.
    """
    print("\nLet's set up your profile so answers fit you. "
          "Type 'skip' at any point to use defaults.\n")
    answers: dict[str, str] = {}
    for i, (key, prompt) in enumerate(_ONBOARD_QUESTIONS):
        try:
            value = input(prompt).strip()
        except EOFError:
            value = ""
        if value.lower() == "skip" or (i == 0 and value == ""):
            agent.skip_onboarding()
            return "Onboarding skipped — a default profile was created. Re-run with 'profile onboard'."
        answers[key] = value
    agent.onboard_profile(answers["style"], answers["constraints"], answers["context"])
    return "Profile created. Refine the style anytime with 'personalize'."


def handle_profile_onboard(agent: JarvisAgent) -> str:
    return run_onboarding(agent, forced=True)


# ── Profile personalisation ──────────────────────────────────────────────────


def handle_personalize(agent: JarvisAgent) -> str:
    """Propose a Style update for profile.md from recent behaviour, then confirm.

    Interactive: shows the current vs proposed Style section and asks for a [y/N]
    before overwriting. Only the '## Style' section of profile.md is ever changed;
    nothing is persisted unless approved.
    """
    current, proposed, error = agent.propose_profile_style()
    if error:
        return error
    if proposed is None:
        return "Recent activity doesn't warrant a style change — profile.md left as is."

    sep = "─" * 60
    print(f"Current Style\n{sep}\n{(current or '(empty)').strip()}\n")
    print(f"Proposed Style\n{sep}\n{proposed.strip()}\n")

    try:
        answer = input("Apply this update to profile.md? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer in ("y", "yes"):
        if agent.apply_profile_style(proposed):
            return "profile.md updated (Style section only)."
        return "Could not update profile.md (no '## Style' section found)."
    return "Discarded — profile.md unchanged."


def handle_session_chat(session_store: SessionStore) -> str:
    return session_store.format_chat()


def handle_session_summary(session_store: SessionStore) -> str:
    return session_store.format_summary()


def handle_session_api(session_store: SessionStore) -> str:
    return session_store.format_api() + "\n"
