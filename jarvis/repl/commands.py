"""
REPL command handlers.

Each handler receives parsed arguments and shared application state, and
returns a string to print. Handlers are pure except `memory edit`, which
launches the user's $EDITOR.
"""

import os
import subprocess

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
  task new [name]               Create a task and link it to this thread
  task list                     List all saved tasks and their stages
  task start <name-or-id>       Resume an existing task in this thread
  task run                      Drive the pipeline autonomously to the next gate or done
  task next                     Advance one stage manually and continue
  task back                     Return validation → execution
  task replan                   Return execution → planning to revise the plan
  task pause                    Unlink the active task (state preserved)
  task delete <name-or-id>      Permanently delete a task
  task done <item>              Record a completed item on the active task
  task todo <item>              Record a remaining item on the active task

  Stages: clarification → planning → execution → validation → done.
  Stage transitions are always enforced in code (ALLOWED_TRANSITIONS). With
  task_autonomy=auto (default), 'task run' rolls forward through stages and stops
  only at a gate: clarification questions, validation failure, or a replan. Backward
  edges (task back / task replan) are always manual. You can also step with 'task next'.

  memory                        List long-term memory files
  memory init                   Scaffold always-on profile.md + invariants.md
  memory edit <name>            Open a memory file in $EDITOR
  memory show <name>            Print a memory file
  memory load <name>            Inject an on-demand memory file into the system prompt
  memory unload <name>          Stop injecting a memory file
  memory write <name> <text>    Create or overwrite a memory file
  memory append <name> <text>   Append a line to a memory file
  memory delete <name>          Delete a memory file

  profile.md and invariants.md are always injected into every prompt (all threads).
  invariants.md is also enforced in code: replies are checked and reworked on violation.

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

  task_autonomy      auto | manual
                             auto   — 'task run' rolls the pipeline forward through
                                      stages to the next gate or done (default)
                             manual — 'task run' executes only the current stage
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
    if task.get("description"):
        lines.append(f"  Goal:    {task['description']}")
    if task.get("plan"):
        lines += ["", "  Plan:"]
        lines += [f"    {ln}" for ln in task["plan"].splitlines()]
    if task.get("completed"):
        lines += ["", "  Completed:"]
        lines += [f"    - {item}" for item in task["completed"]]
    if task.get("remaining"):
        lines += ["", "  Remaining:"]
        lines += [f"    - {item}" for item in task["remaining"]]
    if task.get("notes"):
        lines += ["", f"  Notes:   {task['notes']}"]
    outputs = task.get("stage_outputs") or {}
    ordered = [s for s in ("clarification", "planning", "execution", "validation") if s in outputs]
    if ordered:
        lines += ["", "  Stage results:"]
        for stage in ordered:
            lines.append(f"    [{stage}]")
            lines += [f"      {ln}" for ln in outputs[stage].splitlines()]
    threads = task.get("thread_ids") or []
    if threads:
        lines += ["", f"  Threads: {', '.join(threads)}"]
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
        f"Stage: {task['stage']}. This thread is now linked to it."
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
    return f"Task '{task['name']}' started. Stage: {task['stage']}."


def handle_task_pause(agent: JarvisAgent) -> str:
    name = agent.pause_task()
    if name is None:
        return "No active task to pause."
    return f"Task '{name}' paused and unlinked from this thread (state preserved)."


def handle_task_delete(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: task delete <name-or-id>"
    name = agent.delete_task(" ".join(args))
    if name is None:
        return f"Task not found: '{' '.join(args)}'."
    return f"Task '{name}' deleted."


def handle_task_next(agent: JarvisAgent) -> str:
    if agent.active_task is None:
        return "No active task. Use 'task new <name>' first."
    new_stage, reply = agent.next_stage()
    if new_stage is None:
        return reply  # error message
    return f"[Task moved to stage: {new_stage}]\n\nA: {reply}"


def handle_task_back(agent: JarvisAgent) -> str:
    if agent.active_task is None:
        return "No active task. Use 'task new <name>' first."
    new_stage, reply = agent.back_stage()
    if new_stage is None:
        return reply
    return f"[Task moved to stage: {new_stage}]\n\nA: {reply}"


def handle_task_replan(agent: JarvisAgent) -> str:
    if agent.active_task is None:
        return "No active task. Use 'task new <name>' first."
    new_stage, reply = agent.replan_stage()
    if new_stage is None:
        return reply
    return f"[Task moved to stage: {new_stage}]\n\nA: {reply}"


def handle_task_run(agent: JarvisAgent) -> str:
    """Drive the task pipeline autonomously to the next gate (or done)."""
    if agent.active_task is None:
        return "No active task. Use 'task new <name>' first."
    results = agent.run_task()
    if not results:
        return "No active task. Use 'task new <name>' first."

    blocks: list[str] = []
    for r in results:
        if r.blocked:
            blocks.append(f"[{r.stage}] blocked: {r.blocked}")
            continue
        header = f"[{r.stage}]"
        if r.advanced_to:
            header += f" → {r.advanced_to}"
        blocks.append(f"{header}\n{r.text}")

    last = results[-1]
    if last.blocked:
        footer = "Input requirement not met — resolve it and run 'task run' again."
    elif agent.active_task and agent.active_task["stage"] == "done":
        footer = "Pipeline complete — task is done."
    elif last.verdict and last.verdict.needs_user:
        action = last.verdict.expected_action
        footer = f"Paused for you ({action}). Reply, then run 'task run' to continue."
    else:
        footer = "Paused. Run 'task run' to continue."
    return "\n\n".join(blocks + ["─" * 60, footer])


def handle_task_done(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: task done <item>"
    if not agent.add_completed(" ".join(args)):
        return "No active task. Use 'task new <name>' first."
    return "Recorded completed item."


def handle_task_todo(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: task todo <item>"
    if not agent.add_remaining(" ".join(args)):
        return "No active task. Use 'task new <name>' first."
    return "Recorded remaining item."


# ── Long-term memory ────────────────────────────────────────────────────────


def handle_memory_list(agent: JarvisAgent) -> str:
    from ..session.long_term_memory import ALWAYS_ON
    files = agent.list_memory()
    loaded = agent.loaded_memory
    if not files:
        return "No memory files. Use 'memory init' to scaffold profile + invariants."
    sep = "─" * 60
    lines = [f"Long-Term Memory ({len(files)})", sep]
    for name in files:
        if name in ALWAYS_ON:
            tag = "  [always-on]"
        elif name in loaded:
            tag = "  [loaded]"
        else:
            tag = ""
        lines.append(f"  {name}.md{tag}")
    lines.append(sep)
    lines.append("always-on files inject into every prompt; others: 'memory load <name>'")
    return "\n".join(lines)


def handle_memory_init(agent: JarvisAgent) -> str:
    created = agent.init_memory()
    if not created:
        return "Always-on files already exist (profile.md, invariants.md). Use 'memory edit <name>'."
    return f"Scaffolded: {', '.join(n + '.md' for n in created)}. Edit with 'memory edit <name>'."


def handle_memory_edit(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: memory edit <name>"
    name = args[0]
    # Create an empty file if it does not exist yet, so the editor opens cleanly.
    if agent.read_memory(name) is None:
        agent.write_memory(name, "")
    path = agent.memory_path(name)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    try:
        subprocess.call([editor, str(path)])
    except Exception as exc:  # editor missing / non-interactive
        return f"Could not launch editor ({exc}). Edit the file directly:\n  {path}"
    agent.refresh_memory(name)
    return f"Saved {name}.md."


def handle_memory_show(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: memory show <name>"
    from ..session.long_term_memory import LongTermMemory
    name = LongTermMemory.normalize(args[0])
    content = agent.read_memory(name)
    if content is None:
        return f"Memory file not found: '{name}'."
    sep = "─" * 60
    return f"{name}.md\n{sep}\n{content.rstrip()}\n{sep}"


def handle_memory_load(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: memory load <name>"
    name = agent.load_memory(args[0])
    if name is None:
        return f"Memory file not found: '{args[0]}'."
    return f"Memory '{name}' loaded into the system prompt for this session."


def handle_memory_unload(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: memory unload <name>"
    if not agent.unload_memory(args[0]):
        return f"Memory '{args[0]}' was not loaded."
    return f"Memory '{args[0]}' unloaded."


def handle_memory_write(args: list[str], agent: JarvisAgent) -> str:
    if len(args) < 2:
        return "Usage: memory write <name> <text>"
    name = args[0]
    agent.write_memory(name, " ".join(args[1:]) + "\n")
    return f"Memory '{name}' written."


def handle_memory_append(args: list[str], agent: JarvisAgent) -> str:
    if len(args) < 2:
        return "Usage: memory append <name> <text>"
    name = args[0]
    agent.append_memory(name, " ".join(args[1:]))
    return f"Appended to memory '{name}'."


def handle_memory_delete(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: memory delete <name>"
    if not agent.delete_memory(args[0]):
        return f"Memory file not found: '{args[0]}'."
    return f"Memory '{args[0]}' deleted."


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
