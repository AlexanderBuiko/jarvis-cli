"""
REPL command handlers.

Each handler receives parsed arguments and shared application state, and
returns a string to print. Handlers are pure except `personalize`, which
prompts for confirmation before applying a profile update.
"""

import re
from pathlib import Path

from ..agent import JarvisAgent, _COMPRESSION_INTERVAL
from ..config.manager import ConfigManager
from ..session.store import (
    SessionStore,
    _render_context_chart,
    _render_request_cost_chart,
    _render_cumulative_cost_chart,
)
from ..indexing import IndexPipeline, IndexStore, make_embedder
from ..indexing.chunking import DEFAULT_OVERLAP, DEFAULT_SIZE


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

  mcp list                      List MCP tools available to the agent each turn
  mcp call <tool> [k=v ...]     Call an MCP tool directly (e.g. mcp call weather.get_weather city=London)

  MCP tools are offered to the model automatically on every chat answer and task
  stage; 'mcp' is for inspecting/calling them by hand.

  index build <path> [k=v ...]  Load → chunk → embed → store a document index
  index list                    List saved indexes
  index show [name]             Show an index's header and sample chunks
  index search <query> [k=v]    Semantic search over an index (name=, k=)
  index compare <path> [k=v]    Compare fixed vs structure-aware chunking (query=, size=, overlap=)
  index delete <name>           Delete an index

  rag ask <question> [k=v]      Answer once without RAG vs with RAG, side by side
  rag eval [name=..] [k=v]      Run the 10 control questions and score quality
                                (answers=off → cheap retrieval-only run)

  Indexing builds a local vector index for retrieval (RAG). Embeddings use the
  provider set by JARVIS_EMBED_PROVIDER (default 'ollama'; 'openrouter' optional).
  Chunking has two strategies — 'fixed' (fixed-size with overlap) and 'structure'
  (Markdown headings/sections) — selectable per build and comparable via
  'index compare'. Indexes are JSON under ~/.jarvis/indexes/.

  RAG chat mode: once an index is built, ground your thread's answers in it with
    config set rag on
    config set rag_index <name>      (a name from 'index list')
  Then every prompt-mode message retrieves the top matching chunks, injects them
  into the turn, and the answer cites them as `filename › section`. A per-turn
  notice shows which sources were used. Turn it off with 'config set rag off' to
  compare against the model's general (un-grounded) answer.

  task                          Show the active task (working memory)
  task new [name]               Create a task workspace and enter it
  task list                     List all saved tasks and their stages
  task start <name-or-id>       Enter an existing task workspace
  task run                      Continue the entered task with no new input
  task exit                     Leave the task, back to chat (state preserved)
  task delete <name-or-id>      Permanently delete a task
  task attach <name-or-id>      Pin a finished task's result into this thread's context
  task detach <name-or-id>      Remove an attached task result from this thread

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
  shown and also in 'task show'). The task is then exited and its result is
  attached to the current thread, enriching that chat's context. Use
  'task attach'/'task detach' to manage attachments manually.

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

  review_agents      int    Reviewers on the validation swarm (1–5, default 1). 1 = the single
                            validator; >1 runs an independent reviewer panel + consolidator
                            (~N+1 model calls per validation turn, all billed to the task,
                            run concurrently).

  execution_agents   int    Agents executing the plan in parallel (1–8, default 1). 1 = sequential,
                            one step per turn; >1 runs independent steps concurrently, ordering
                            dependent ones via the plan's [after: …] annotations.

  rag                bool   Ground chat answers in a local index (default off). When on, each
                            prompt-mode message retrieves chunks and the answer cites the source.
  rag_index          str    Name of the index to retrieve from (see 'index list').
  rag_k              int    Chunks retrieved per message (1–20, default 5).
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
    attachments = agent.list_attachments()
    if not history and not attachments:
        return "Conversation history is empty."
    turn_count = len(history) // 2
    tok = agent.thread_total_tokens
    cost = agent.thread_total_cost
    tok_str = f"{tok:,} tokens" if tok else "0 tokens"
    cost_str = f"  ${cost:.6f}" if cost else ""
    lines = [f"Conversation context ({turn_count} turn(s))  —  {tok_str}{cost_str}", ""]
    if attachments:
        names = ", ".join(f"{a['name']}" for a in attachments)
        lines += [f"Attached task results ({len(attachments)}): {names}", ""]
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
    width = len(str(len(steps)))

    # Parallel execution publishes a live per-step status (several steps can be
    # in-progress at once); prefer it so the table reflects real concurrency. Falls
    # back to the single-cursor step_index model for sequential execution.
    status = task.get("_step_status")
    if status and len(status) == len(steps):
        glyphs = {"done": "✓", "running": "▶", "pending": "○"}
        done = sum(1 for s in status if s == "done")
        lines = [f"Steps ({done}/{len(steps)} done)"]
        for i, step in enumerate(steps):
            lines.append(f"  {glyphs.get(status[i], '○')}  {str(i + 1).rjust(width)}. {step}")
        return "\n".join(lines)

    idx = task.get("step_index", 0)
    done = min(idx, len(steps))
    lines = [f"Steps ({done}/{len(steps)} done)"]
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

    # LLM spend accumulated across this task's stage turns.
    calls = task.get("api_call_count", 0)
    if calls:
        tok = task.get("total_tokens", 0)
        cost = task.get("total_cost", 0.0)
        cost_str = f"${cost:.6f}" if cost else "—"
        lines += ["", f"  Spend:   {calls} request(s) · {tok:,} tokens · {cost_str}"]

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


def handle_task_attach(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: task attach <name-or-id>"
    query = " ".join(args)
    name = agent.attach_task(query)
    if name is None:
        return (
            f"Could not attach '{query}'. The task must exist and have a finished "
            "result (run it to 'done' first)."
        )
    return f"Attached task '{name}' result to thread '{agent.thread_name}'. It now enriches this chat's context."


def handle_task_detach(args: list[str], agent: JarvisAgent) -> str:
    if not args:
        return "Usage: task detach <name-or-id>"
    query = " ".join(args)
    name = agent.detach_task(query)
    if name is None:
        return f"No attached task matching '{query}'."
    return f"Detached task '{name}' from thread '{agent.thread_name}'."


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


# ── MCP (Model Context Protocol tools) ───────────────────────────────────────


def handle_mcp(args: list[str], agent: JarvisAgent) -> str:
    """Inspect and call MCP tools — a debug/ops view of the same fleet the agent uses.

    `mcp list`                  → list every aggregated tool
    `mcp call <tool> [k=v ...]` → invoke a tool and print its result

    When the agent has a live tool provider (the normal case), these run against
    that already-connected fleet. Otherwise they fall back to an ad-hoc connect so
    the commands still work as a connectivity check. The agent calls these same
    tools automatically each turn; this command is for inspecting them directly.
    """
    sub = args[0].lower() if args else "list"
    provider = agent.tool_provider

    try:
        from ..mcp.cli import _parse_kwargs
    except ImportError:
        return "MCP support isn't installed. Run: pip install 'mcp>=1.8'"

    try:
        if provider is not None:
            return _handle_mcp_live(sub, args, provider, _parse_kwargs)
        return _handle_mcp_adhoc(sub, args, _parse_kwargs)
    except Exception as exc:  # boundary: report, don't crash the REPL
        return f"MCP error: {exc}"


def _handle_mcp_live(sub, args, provider, parse_kwargs) -> str:
    """Run against the agent's already-connected provider."""
    if sub == "list":
        tools = provider.tools()
        lines = [f"✓ Live: {', '.join(provider.connected_servers) or '(none)'}"]
        for server, err in provider.failures.items():
            lines.append(f"✗ {server}: {err}")
        lines += ["", f"Tools ({len(tools)}):"]
        for t in tools:
            summary = (t.description or "").splitlines()[0] if t.description else ""
            lines.append(f"  • {t.qualified_name:<24} {summary}")
        return "\n".join(lines)
    if sub == "call":
        if len(args) < 2:
            return "Usage: mcp call <tool> [key=value ...]"
        return provider.call_tool(args[1], parse_kwargs(args[2:]))
    return "Usage: mcp list | mcp call <tool> [key=value ...]"


def _handle_mcp_adhoc(sub, args, parse_kwargs) -> str:
    """No live provider: open a throwaway connection for this command only."""
    import asyncio
    from ..mcp.cli import _list as mcp_list, _call as mcp_call

    if sub == "list":
        return asyncio.run(mcp_list())
    if sub == "call":
        if len(args) < 2:
            return "Usage: mcp call <tool> [key=value ...]"
        return asyncio.run(mcp_call(args[1], parse_kwargs(args[2:])))
    return "Usage: mcp list | mcp call <tool> [key=value ...]"


# ── Document indexing (RAG) ───────────────────────────────────────────────────

_INDEX_USAGE = (
    "Usage:\n"
    "  index build <path> [name=..] [strategy=fixed|structure] [size=..] [overlap=..] [provider=..] [model=..]\n"
    "  index list\n"
    "  index show [name]\n"
    "  index search <query words…> [name=..] [k=5]\n"
    "  index compare <path> [size=..] [overlap=..] [query=\"one word per token\"]\n"
    "  index delete <name>"
)


def handle_index(args: list[str]) -> str:
    """Build, inspect, search, and compare local document indexes.

    Embeddings use the provider from JARVIS_EMBED_PROVIDER (default 'ollama').
    Search re-uses the *index's own* provider/model (recorded in its header) so a
    query is always embedded the same way the index was — the seam the follow-up
    RAG task builds on.
    """
    sub = args[0].lower() if args else "list"
    rest = args[1:]
    try:
        if sub == "build":
            return _index_build(rest)
        if sub == "list":
            return _index_list()
        if sub == "show":
            return _index_show(rest)
        if sub == "search":
            return _index_search(rest)
        if sub == "compare":
            return _index_compare(rest)
        if sub == "delete":
            return _index_delete(rest)
        return _INDEX_USAGE
    except Exception as exc:  # boundary: report, don't crash the REPL
        return f"Index error: {exc}"


def _split_index_args(args: list[str]) -> tuple[list[str], dict]:
    """Separate bare positional tokens from key=value options."""
    positional: list[str] = []
    opts: dict[str, str] = {}
    for a in args:
        if "=" in a and not a.startswith("="):
            key, _, val = a.partition("=")
            opts[key.strip().lower()] = val.strip()
        else:
            positional.append(a)
    return positional, opts


def _default_index_name(path: str, strategy: str) -> str:
    base = Path(path).resolve().name or "index"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "index"
    return f"{slug}-{strategy}"


def _index_build(args: list[str]) -> str:
    positional, opts = _split_index_args(args)
    if not positional:
        return _INDEX_USAGE
    path = positional[0]
    strategy = opts.get("strategy", "structure")
    name = opts.get("name") or _default_index_name(path, strategy)
    size = int(opts.get("size", DEFAULT_SIZE))
    overlap = int(opts.get("overlap", DEFAULT_OVERLAP))
    embedder = make_embedder(opts.get("provider"), opts.get("model"))
    pipeline = IndexPipeline(embedder)
    res = pipeline.build(path, name, strategy=strategy, size=size, overlap=overlap)
    return (
        f"Built index '{res.name}'\n"
        f"  strategy:   {res.strategy}  (size={res.size}, overlap={res.overlap} chars)\n"
        f"  embeddings: {res.provider} / {res.model}  ({res.dim}-dim)\n"
        f"  documents:  {res.n_documents}\n"
        f"  chunks:     {res.n_chunks}\n"
        f"  saved to:   {res.path}\n"
        f"Search it:  index search <your question> name={res.name}"
    )


def _index_list() -> str:
    items = IndexStore().list_all()
    if not items:
        return "No indexes yet. Build one:  index build <path>"
    sep = "─" * 78
    lines = [f"Indexes ({len(items)})", sep,
             f"  {'name':<26} {'strategy':<10} {'chunks':>6}  {'provider/model'}"]
    for h in items:
        pm = f"{h.get('provider', '?')}/{h.get('model', '?')}"
        lines.append(
            f"  {h.get('name', '?'):<26} {h.get('strategy', '?'):<10} "
            f"{h.get('n_chunks', 0):>6}  {pm}"
        )
    lines.append(sep)
    return "\n".join(lines)


def _resolve_index_name(positional: list[str], opts: dict) -> str | None:
    """Pick the index name from a positional arg, name=, or the most recent."""
    name = opts.get("name") or (positional[0] if positional else None)
    if name:
        return name
    items = IndexStore().list_all()
    return items[0]["name"] if items else None


def _index_show(args: list[str]) -> str:
    positional, opts = _split_index_args(args)
    name = _resolve_index_name(positional, opts)
    if not name:
        return "No indexes yet. Build one:  index build <path>"
    loaded = IndexStore().load(name)
    if loaded is None:
        return f"No such index: '{name}'. Use 'index list'."
    header, records = loaded
    sep = "─" * 78
    lines = [
        f"Index '{name}'", sep,
        f"  strategy:   {header.get('strategy')}  (size={header.get('size')}, overlap={header.get('overlap')})",
        f"  embeddings: {header.get('provider')} / {header.get('model')}  ({header.get('dim')}-dim)",
        f"  documents:  {header.get('n_documents')}   chunks: {header.get('n_chunks')}",
        f"  created:    {header.get('created_at')}",
        "", "  Sample chunks:",
    ]
    for rec in records[:5]:
        md = rec["metadata"]
        preview = " ".join(rec["text"].split())[:70]
        lines.append(
            f"    [{md['chunk_id']}]  {md['filename']} › {md['section']}  ({md['n_chars']} chars)"
        )
        lines.append(f"        {preview}…")
    lines.append(sep)
    return "\n".join(lines)


def _index_search(args: list[str]) -> str:
    positional, opts = _split_index_args(args)
    query = " ".join(positional).strip()
    if not query:
        return "Usage: index search <query words…> [name=..] [k=5]"
    name = opts.get("name") or _resolve_index_name([], opts)
    if not name:
        return "No indexes yet. Build one:  index build <path>"
    store = IndexStore()
    header = store.load_header(name)
    if header is None:
        return f"No such index: '{name}'. Use 'index list'."
    k = int(opts.get("k", 5))
    # Embed the query with the index's own provider/model for a valid comparison.
    embedder = make_embedder(
        opts.get("provider") or header.get("provider"),
        opts.get("model") or header.get("model"),
    )
    results = IndexPipeline(embedder, store).search(name, query, k)
    if not results:
        return f"No results in index '{name}'."
    sep = "─" * 78
    lines = [f"Top {len(results)} for: “{query}”   (index '{name}')", sep]
    for i, r in enumerate(results, 1):
        md = r["metadata"]
        preview = " ".join(r["text"].split())[:160]
        lines.append(f"  {i}. score={r['score']:.4f}  {md['filename']} › {md['section']}")
        lines.append(f"     [{md['chunk_id']}]  {preview}…")
    lines.append(sep)
    return "\n".join(lines)


def _index_compare(args: list[str]) -> str:
    positional, opts = _split_index_args(args)
    if not positional:
        return "Usage: index compare <path> [size=..] [overlap=..] [query=..]"
    path = positional[0]
    size = int(opts.get("size", DEFAULT_SIZE))
    overlap = int(opts.get("overlap", DEFAULT_OVERLAP))
    query = opts.get("query")
    embedder = make_embedder(opts.get("provider"), opts.get("model"))
    stats = IndexPipeline(embedder).compare(path, size=size, overlap=overlap, query=query)
    sep = "─" * 78
    lines = [
        f"Chunking comparison for: {path}   (size={size}, overlap={overlap})", sep,
        f"  {'strategy':<12} {'chunks':>7} {'avg':>7} {'min':>7} {'max':>7}   (chars)",
    ]
    for s in stats:
        lines.append(
            f"  {s.strategy:<12} {s.n_chunks:>7} {s.avg_chars:>7} {s.min_chars:>7} {s.max_chars:>7}"
        )
    if query:
        lines += ["", f"  Top hits for “{query}”:"]
        for s in stats:
            lines.append(f"    [{s.strategy}]")
            for score, filename, section in s.top_hits:
                lines.append(f"      score={score:.4f}  {filename} › {section}")
    lines.append(sep)
    return "\n".join(lines)


def _index_delete(args: list[str]) -> str:
    positional, _ = _split_index_args(args)
    if not positional:
        return "Usage: index delete <name>"
    name = positional[0]
    return (
        f"Deleted index '{name}'." if IndexStore().delete(name)
        else f"No such index: '{name}'."
    )


# ── RAG comparison & evaluation ──────────────────────────────────────────────

_RAG_USAGE = (
    "Usage:\n"
    "  rag ask <question words…> [name=..] [k=5]      Answer once without vs with RAG\n"
    "  rag eval [name=..] [k=5] [answers=on|off]      Run the control questions + score\n"
    "Note: both call the chat model (rag ask = 2 calls; rag eval = ~2×questions).\n"
    "      'answers=off' makes eval retrieval-only (cheap — no chat calls)."
)


def handle_rag(args: list[str], agent: JarvisAgent, config_manager: ConfigManager) -> str:
    """Compare un-grounded vs RAG-grounded answers, and score the control set."""
    sub = args[0].lower() if args else ""
    rest = args[1:]
    try:
        if sub == "ask":
            return _rag_ask(rest, agent, config_manager)
        if sub == "eval":
            return _rag_eval(rest, agent, config_manager)
        return _RAG_USAGE
    except Exception as exc:  # boundary: report, don't crash the REPL
        return f"RAG error: {exc}"


def _resolve_rag_index(opts: dict, config_manager: ConfigManager) -> str | None:
    """Index name from name=, else the configured rag_index, else most recent."""
    name = opts.get("name") or config_manager.runtime.get("rag_index")
    if name:
        return name
    items = IndexStore().list_all()
    return items[0]["name"] if items else None


def _rag_ask(args: list[str], agent: JarvisAgent, config_manager: ConfigManager) -> str:
    positional, opts = _split_index_args(args)
    question = " ".join(positional).strip()
    if not question:
        return "Usage: rag ask <question words…> [name=..] [k=5]"
    index = _resolve_rag_index(opts, config_manager)
    if not index:
        return "No index to retrieve from. Build one:  index build <path>"
    k = int(opts.get("k", 5))
    plain, grounded, results, error = agent.compare_rag(question, index, k)
    sep = "─" * 78
    lines = [f"Question: {question}", f"Index: {index}  (k={k})", "",
             sep, "Without RAG (model's general knowledge)", sep, plain, ""]
    if error:
        lines += [sep, f"With RAG — unavailable: {error}", sep]
    else:
        srcs = []
        for r in results:
            fn = r["metadata"].get("filename", "?")
            if fn not in srcs:
                srcs.append(fn)
        lines += [sep, f"With RAG (sources: {', '.join(srcs)})", sep, grounded or "(no answer)"]
    return "\n".join(lines)


def _rag_eval(args: list[str], agent: JarvisAgent, config_manager: ConfigManager) -> str:
    from ..rag import load_questions, evaluate, format_report, DEFAULT_QUESTIONS_PATH

    positional, opts = _split_index_args(args)
    index = _resolve_rag_index(opts, config_manager)
    if not index:
        return "No index to evaluate against. Build one:  index build <path>"
    k = int(opts.get("k", 5))
    generate = opts.get("answers", "on").lower() not in ("off", "false", "no", "0")
    questions = load_questions(opts.get("questions") or DEFAULT_QUESTIONS_PATH)
    report = evaluate(agent, questions, index, k=k, generate_answers=generate)
    return format_report(report)


def handle_session_chat(session_store: SessionStore) -> str:
    return session_store.format_chat()


def handle_session_summary(session_store: SessionStore) -> str:
    return session_store.format_summary()


def handle_session_api(session_store: SessionStore) -> str:
    return session_store.format_api() + "\n"
