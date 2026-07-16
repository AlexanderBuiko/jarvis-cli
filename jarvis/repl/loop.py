"""
REPL loop.

Reads user input via InputController and routes it by input type:
  "prompt"  → message forwarded to JarvisAgent
  "command" → text dispatched to command handlers

All conversation and LLM logic lives in the agent; this module is pure UI.
"""

import itertools
import os
import shutil
import sys
import threading
import time
from typing import Callable

from .commands import (
    handle_help,
    handle_help_query,
    handle_support_query,
    handle_config_show,
    handle_config_set,
    handle_config_update,
    handle_config_reset,
    handle_thread_show,
    handle_thread_clear,
    handle_thread_load,
    handle_thread_new,
    handle_thread_rename,
    handle_thread_delete,
    handle_thread_summary,
    handle_thread_state,
    handle_session_chat,
    handle_session_summary,
    handle_session_api,
    handle_task_show,
    handle_task_new,
    handle_task_list,
    handle_task_start,
    handle_task_exit,
    handle_task_delete,
    handle_task_attach,
    handle_task_detach,
    handle_invariants_show,
    handle_invariants_init,
    handle_profile_show,
    handle_profile_onboard,
    handle_personalize,
    handle_mcp,
    handle_index,
    handle_rag,
    handle_quiz,
    run_onboarding,
    render_plan_progress,
)
from .input import InputController
from ..agent import JarvisAgent
from ..config.manager import ConfigManager
from ..openrouter.client import DEFAULT_MODEL
from ..pipeline.base import GATE_APPROVAL, GATE_QUESTION


def _active_provider_model(config_manager: ConfigManager) -> tuple[str, str]:
    """(provider, effective model) for the current toggle — for status/context display.

    On the local provider a cloud model id in ``model`` is meaningless, so the local
    engine's own default is shown instead (matching what it will actually run).
    """
    from ..llm.router import current_provider
    provider = current_provider(config_manager)
    configured = config_manager.runtime.get("model")
    if provider == "ollama":
        from ..ollama.client import DEFAULT_MODEL as OLLAMA_DEFAULT
        model = configured if (configured and "/" not in configured) else (
            os.environ.get("JARVIS_OLLAMA_MODEL") or OLLAMA_DEFAULT
        )
    else:
        model = configured or DEFAULT_MODEL
    return provider, model


def run_repl(agent: JarvisAgent, config_manager: ConfigManager, tool_gate=None) -> None:
    print(_banner())

    # First run: no profile yet → offer the onboarding interview (skippable).
    if not agent.profile_exists():
        try:
            print(run_onboarding(agent))
        except (EOFError, KeyboardInterrupt):
            agent.skip_onboarding()
            print("\nOnboarding skipped — a default profile was created.")
        print()

    print("Starts in prompt mode (>). Type ! on an empty line to switch modes.\n")

    def _status_fn() -> str:
        # Inside a task workspace, show the task instead of the (unused) thread tokens.
        task = agent.active_task
        if task:
            return f"task: {task['name']}  ·  stage: {task['stage']}"
        tokens = agent.last_context_tokens
        provider, model = _active_provider_model(config_manager)
        ctx = agent.get_context_window(model)
        head = f"{provider}:{model}"
        if ctx:
            pct = round(tokens * 100 / ctx)
            return f"{head}  ·  chat: {tokens:,}/{ctx:,} ({pct}%) tokens"
        return f"{head}  ·  chat: {tokens:,} tokens"

    def _progress_fn() -> str:
        """Live plan-progress panel shown above the input during execution/validation."""
        task = agent.active_task
        if not task or task.get("stage") not in ("execution", "validation"):
            return ""
        return render_plan_progress(task) or ""

    def _hint_fn() -> str:
        """Task-aware placeholder so an in-progress task doesn't show the generic hint."""
        task = agent.active_task
        if not task or task.get("stage") == "done":
            return ""
        return f"Task '{task['name']}' ({task['stage']}) — type your message to continue, or 'task run'."

    controller = InputController(status_fn=_status_fn, progress_fn=_progress_fn, hint_fn=_hint_fn)

    while True:
        try:
            input_type, raw = controller.read_input()
        except EOFError:
            print("\nGoodbye.")
            sys.exit(0)

        if input_type == "command":
            output = _dispatch(raw, agent, config_manager, controller)
        else:
            task = agent.active_task
            if task and task.get("stage") != "done":
                # An active task owns prompt input: this message drives its pipeline.
                output = _drive_task(agent, controller, initial_pending=f"The user says: {raw}")
            else:
                _drain_live_notes()  # discard any stale notes (e.g. from a task run)
                try:
                    (answer, _notices), _ = _run_with_spinner(
                        lambda: agent.chat_detailed(raw), note_fn=_live_notes
                    )
                    output = _format_answer(answer)
                except Exception as exc:
                    output = f"Error: {exc}"
                # The turn may have produced dry-run previews (show them read-only) and
                # queued real writes for approval; handle both now, on the main thread
                # with the spinner stopped (the worker that ran the turn can't prompt).
                _show_previews(tool_gate, controller)
                _process_pending_writes(tool_gate, agent.tool_provider, controller)

        if output:
            print(output)
            print()


# ── Interactive task driver ─────────────────────────────────────────────────────

# Safety cap on driver iterations (a misbehaving model can't loop forever).
_MAX_DRIVE_TURNS = 80

# ANSI colours for the live step table, by status glyph.
_STEP_ANSI = {"✓": "\033[32m", "▶": "\033[33m", "○": "\033[90m"}
_ANSI_RESET = "\033[0m"

# Colours for the per-turn trace / answer split. Suppressed when stdout isn't a TTY
# (piped/redirected) so raw escape codes don't leak into captured output.
_COLOR = sys.stdout.isatty()
_DIM = "\033[90m" if _COLOR else ""       # generic notice / trace: dim grey
_ANSWER = "\033[36;1m" if _COLOR else ""  # answer label: bold cyan
_TOOL = "\033[36m" if _COLOR else ""      # mcp tool-call note: cyan
_RAG = "\033[35m" if _COLOR else ""       # rag-request note: magenta
_SAY = "\033[37m" if _COLOR else ""       # model's intent narration: soft white
_RESET = "\033[0m" if _COLOR else ""


class _LiveRegion:
    """A multi-line terminal region that redraws in place (cursor-up + clear)."""

    def __init__(self) -> None:
        self._lines = 0

    def render(self, lines: list[str]) -> None:
        out = []
        if self._lines:
            out.append(f"\033[{self._lines}A")   # cursor up to the region's top
        out.append("\033[J")                     # clear from cursor to end of screen
        out.append("\n".join(lines) + "\n")
        sys.stdout.write("".join(out))
        sys.stdout.flush()
        self._lines = len(lines)

    def finalize(self) -> None:
        """Leave the current content on screen and stop tracking it."""
        self._lines = 0


def _parse_dry_run(content: str) -> tuple[str, str]:
    """Split a dry-run tool result into (action, diff): the "[dry run — would …]" banner
    names the action; the rest is the diff."""
    banner, _, rest = content.partition("\n")
    if banner.startswith("[dry run"):
        action = ("create" if "create" in banner else "delete" if "delete" in banner
                  else "update")
        return action, rest
    return "update", content


def _show_previews(tool_gate, controller: InputController) -> None:
    """Render the turn's dry-run diffs as read-only frames (nothing is written)."""
    if tool_gate is None or not hasattr(tool_gate, "take_previews"):
        return
    for item in tool_gate.take_previews():
        action, diff = _parse_dry_run(item["content"])
        controller.show_preview(item["path"], diff, action=action)


def _process_pending_writes(tool_gate, provider, controller: InputController) -> None:
    """Approve/apply the writes the last turn queued (main thread, spinner stopped).

    For each pending write: show the diff (a dry-run peek at the same tool), then ask
    apply-once / apply-and-allow-all / skip via the standard select menu. Applying calls
    the tool directly (past the gate, since the user just approved it); the journal makes
    it revertible. 'Allow all' grants the tool for the rest of the session.
    """
    if tool_gate is None or provider is None:
        return
    for item in tool_gate.take_pending():
        tool, args = item["tool"], item["args"]
        path = args.get("path", "the file")
        # Peek at the diff without writing, then let the user approve it from a compact,
        # expandable frame (not a full-file dump). Strip the "[dry run …]" banner.
        try:
            preview = provider.call_tool(tool, {**args, "dry_run": True})
        except Exception as exc:  # noqa: BLE001 — preview is best-effort
            preview = f"(could not preview: {exc})"
        # The dry-run banner names the action ("would create/update/delete"); use it to
        # colour/label the frame. Strip the banner line before showing the diff.
        action, diff = _parse_dry_run(preview)
        decision = controller.approve_write(path, diff, action=action)
        if decision == "always":
            tool_gate.grant_always(tool)
        if decision in ("once", "always"):
            apply_args = {k: v for k, v in args.items() if k != "dry_run"}
            try:
                result = provider.call_tool(tool, apply_args)
                # One-line confirmation — the frame already showed the change; don't
                # re-dump the whole file.
                head = result.splitlines()[0] if result else f"[wrote {path}]"
                print(f"{_TOOL}✓ {head}{_RESET}  ·  revert: files.revert_file path={path}")
            except Exception as exc:  # noqa: BLE001
                print(f"Error applying change to {path}: {exc}")
        else:
            print(f"{_DIM}✗ skipped {path} — nothing was written{_RESET}")


def _color_step_line(line: str) -> str:
    colour = _STEP_ANSI.get(line.lstrip()[:1])
    return f"{colour}{line}{_ANSI_RESET}" if colour else line


def _drive_task(agent: JarvisAgent, controller: InputController, initial_pending: str = "") -> str:
    """Drive the active task's pipeline interactively to the next pause or done.

    Execution runs under a live step table (updated in place as each step
    completes) with a spinner+timer beneath it. Other stages run with the plain
    spinner. Pauses at gates: a free-text question, or a Confirm/Reject approval
    (only at plan approval and the final done decision). initial_pending seeds the
    first turn (e.g. the task request captured at 'task new').
    """
    if agent.active_task is None:
        return "No active task. Use 'task new <name>' first."

    pending = initial_pending
    for _ in range(_MAX_DRIVE_TURNS):
        stage = agent.active_task["stage"] if agent.active_task else None
        if stage is None:
            return "No active task."

        if stage == "execution":
            outcome, pending = _drive_execution(agent, controller, pending)
            if outcome == "stopped":
                return "■ Stopped. The last completed step is saved — run 'task run' to resume."
            if outcome == "error":
                return pending  # carries the error message
            continue  # left execution (advanced) or handled an inline question

        feedback, pending = pending, ""
        try:
            result, interrupted = _run_with_spinner(
                lambda: agent.pipeline_step(feedback), status_fn=lambda: stage
            )
        except Exception as exc:
            return f"Error: {exc}"
        if result is None:
            return "No active task."
        if result.blocked:
            return f"[{result.stage}] cannot start: {result.blocked}"

        # Done stage: split the one-line summary from the full deliverable; save the
        # deliverable to a file and show only the short description + path.
        if agent.active_task and agent.active_task["stage"] == "done":
            summary, deliverable = _split_summary(result.text)
            path = agent.save_task_result(deliverable)
            thread = agent.thread_name
            # On completion, the result is attached to the active thread and the
            # task is exited — enriching the thread's context with the deliverable.
            name = agent.finish_active_task(summary, deliverable)
            print(f"[done] {summary}\n")
            return (
                f"✓ Task '{name}' complete. Result saved to {path} and attached to "
                f"thread '{thread}' (use it in chat; 'task detach {name}' to remove)."
            )

        header = f"[{result.stage}]"
        if result.advanced_to:
            header += f" → {result.advanced_to}"
        task_now = agent.active_task
        if task_now and task_now.get("api_call_count"):
            header += f"  ·  {task_now['api_call_count']} reqs · ${task_now.get('total_cost', 0.0):.6f}"
        print(f"{header}\n{result.text}\n")

        if interrupted:
            return "■ Stopped. The last completed step is saved — run 'task run' to resume."

        verdict = result.verdict
        if verdict and verdict.gate == GATE_APPROVAL:
            title, choices = _approval_choices(result.stage, verdict)
            choice = controller.select(title, [label for label, _ in choices])
            if choice is None or choice < 0 or choice >= len(choices):
                print(f"{title}  →  (cancelled)\n")
                return "Paused. Run 'task run' to resume."
            label, target = choices[choice]
            print(f"{title}  →  {label}\n")  # replaces the erased arrow menu
            if choice == 0:
                # The Confirm choice: advance with no rework feedback.
                agent.advance_to(target)
                continue
            # A reject-style choice: gather feedback and route to its target.
            problem = controller.read_text("What's the problem?")
            agent.advance_to(target)
            pending = (
                f"The user rejected this and asked for changes: {problem}\nRevise accordingly."
                if problem else "The user rejected this; please revise."
            )
            continue

        if verdict and verdict.gate == GATE_QUESTION:
            answer = controller.read_text("Your answer:")
            if not answer:
                return "Paused. Run 'task run' to resume."
            pending = f"The user responded: {answer}"
            continue

    return "Stopped after the step cap. Run 'task run' to continue."


def _exec_panel(agent: JarvisAgent, frame: str, elapsed: float, interrupted: bool,
                final: bool = False) -> list[str]:
    """Build the live execution panel: the step table plus a spinner+timer line.

    Every line is truncated to the terminal width so each occupies exactly one
    visual row — that keeps the in-place redraw's cursor-up count exact (wrapped
    lines would otherwise make the panel accumulate).
    """
    width = max(20, shutil.get_terminal_size((80, 24)).columns)
    table = render_plan_progress(agent.active_task) or "Executing…"
    lines = []
    for ln in table.split("\n"):
        if len(ln) > width:
            ln = ln[: width - 1] + "…"
        lines.append(_color_step_line(ln))
    if not final:
        if interrupted:
            spin = f"{frame} Stopping {elapsed:4.1f}s  ·  finishing current step…"
        else:
            spin = f"{frame} Working… {elapsed:4.1f}s  ·  Ctrl+C to stop"
        lines += ["", spin[:width]]
    return lines


def _drive_execution(agent: JarvisAgent, controller: InputController, pending: str):
    """Drive the execution stage under a live, in-place step table. Returns (outcome, carry)."""
    region = _LiveRegion()
    frames = itertools.cycle(_SPINNER_FRAMES)
    while agent.active_task and agent.active_task["stage"] == "execution":
        feedback, pending = pending, ""
        box: dict = {}

        def _worker() -> None:
            try:
                box["result"] = agent.pipeline_step(feedback)
            except BaseException as exc:
                box["error"] = exc

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        start = time.perf_counter()
        interrupted = False
        while worker.is_alive():
            try:
                region.render(_exec_panel(agent, next(frames), time.perf_counter() - start, interrupted))
                worker.join(0.12)
            except KeyboardInterrupt:
                interrupted = True

        if "error" in box:
            region.render(_exec_panel(agent, " ", time.perf_counter() - start, False, final=True))
            region.finalize()
            return "error", f"Error: {box['error']}"

        result = box.get("result")
        # Final redraw shows the table after this step completed.
        region.render(_exec_panel(agent, " ", time.perf_counter() - start, interrupted, final=True))

        if interrupted:
            region.finalize()
            return "stopped", ""
        if result is None or result.blocked:
            region.finalize()
            return "left", ""

        verdict = result.verdict
        if verdict and verdict.gate == GATE_QUESTION:
            region.finalize()
            print(f"\n{result.text}\n")
            answer = controller.read_text("Your answer:")
            if not answer:
                return "stopped", ""
            pending = f"The user responded: {answer}"
            region = _LiveRegion()
            continue
        # Step done / advanced — loop; if execution was left, the while exits.

    region.finalize()
    return "left", pending


def _split_summary(text: str) -> tuple[str, str]:
    """Split a done-stage reply into (short_summary, deliverable).

    Expects a leading 'SUMMARY: <one line>' then the deliverable. Falls back to
    the first non-empty line as the summary and the whole text as the deliverable.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith("SUMMARY:"):
            summary = stripped[len("SUMMARY:"):].strip()
            deliverable = "\n".join(lines[i + 1:]).strip()
            return (summary or "Task complete."), (deliverable or text.strip())
        break
    first = next((ln.strip() for ln in lines if ln.strip()), "Task complete.")
    return first[:200], text.strip()


def _approval_choices(stage: str, verdict) -> tuple[str, list[tuple[str, str | None]]]:
    """Return (title, [(label, target_stage), ...]) for an approval gate.

    The first choice is always the Confirm (advance, no feedback); the rest are
    reject-style choices (ask for feedback, then route to their target). Validation
    is user-driven with three choices — mark done, rework execution, or revise the
    plan — so the user always controls a re-plan, not the model.
    """
    if stage == "planning":
        return (
            "Approve this plan?",
            [
                ("Confirm — start execution", verdict.confirm_target),
                ("Reject — revise the plan", verdict.reject_target),
            ],
        )
    if stage == "validation":
        replan_label = "Reject — revise the plan"
        if getattr(verdict, "replan_recommended", False):
            replan_label += "  (recommended)"
        return (
            "Validation complete — what next?",
            [
                ("Confirm — mark done", verdict.confirm_target),
                ("Reject — rework execution", verdict.reject_target),
                (replan_label, verdict.replan_target),
            ],
        )
    return (
        "Proceed?",
        [("Confirm", verdict.confirm_target), ("Reject", verdict.reject_target)],
    )


# ── Dispatcher ────────────────────────────────────────────────────────────────


def _dispatch(
    raw: str,
    agent: JarvisAgent,
    config_manager: ConfigManager,
    controller: "InputController",
) -> str:
    tokens = raw.split()
    if not tokens:
        return ""
    cmd = tokens[0].lower()
    args = tokens[1:]

    if cmd in ("exit", "quit"):
        print("Goodbye.")
        sys.exit(0)

    if cmd == "help":
        if args:
            return handle_help_query(" ".join(args), agent)
        return handle_help()

    if cmd == "support":
        return handle_support_query(args, agent)

    if cmd == "config":
        if not args:
            return "Usage: config show | config set <key> <value> | config update <k=v>... | config reset"
        sub = args[0].lower()
        if sub == "show":
            return handle_config_show(config_manager)
        if sub == "set":
            locked = _locked_param_error("set", args[1:], agent)
            if locked:
                return locked
            return handle_config_set(args[1:], config_manager)
        if sub == "reset":
            return handle_config_reset(config_manager)
        if sub == "update":
            locked = _locked_param_error("update", args[1:], agent)
            if locked:
                return locked
            return handle_config_update(args[1:], config_manager)
        return f"Unknown config sub-command: '{sub}'"

    if cmd == "thread":
        if not args:
            return handle_thread_show(agent)
        sub = args[0].lower()
        if sub == "clear":
            return handle_thread_clear(agent)
        if sub == "load":
            return handle_thread_load(args[1:], agent)
        if sub == "new":
            return handle_thread_new(args[1:], agent)
        if sub == "rename":
            return handle_thread_rename(args[1:], agent)
        if sub == "delete":
            return handle_thread_delete(args[1:], agent)
        if sub == "summary":
            _, model = _active_provider_model(config_manager)
            ctx = agent.get_context_window(model)
            return handle_thread_summary(agent, ctx)
        if sub == "state":
            return handle_thread_state(agent)
        return "Usage: thread | thread clear | thread load [<name-or-id>] | thread new [name] | thread rename <name> | thread delete <name-or-id> | thread summary | thread state"

    if cmd == "task":
        if not args:
            return handle_task_show(agent)
        sub = args[0].lower()
        if sub == "new":
            return handle_task_new(args[1:], agent)
        if sub == "list":
            return handle_task_list(agent)
        if sub == "show":
            return handle_task_show(agent)
        if sub == "start":
            return handle_task_start(args[1:], agent)
        if sub == "run":
            return _drive_task(agent, controller)
        if sub == "exit":
            return handle_task_exit(agent)
        if sub == "delete":
            return handle_task_delete(args[1:], agent)
        if sub == "attach":
            return handle_task_attach(args[1:], agent)
        if sub == "detach":
            return handle_task_detach(args[1:], agent)
        return (
            "Usage: task | task new [name] | task list | task start <name-or-id> | "
            "task run | task exit | task delete <name-or-id> | "
            "task attach <name-or-id> | task detach <name-or-id>"
        )

    if cmd == "invariants":
        if not args:
            return handle_invariants_show(agent)
        sub = args[0].lower()
        if sub == "show":
            return handle_invariants_show(agent)
        if sub == "init":
            return handle_invariants_init(agent)
        return "Usage: invariants | invariants init"

    if cmd == "profile":
        if not args:
            return handle_profile_show(agent)
        sub = args[0].lower()
        if sub == "show":
            return handle_profile_show(agent)
        if sub == "onboard":
            return handle_profile_onboard(agent)
        return "Usage: profile | profile onboard"

    if cmd == "personalize":
        return handle_personalize(agent)

    if cmd == "mcp":
        return handle_mcp(args, agent)

    if cmd == "index":
        return handle_index(args)

    if cmd == "rag":
        return handle_rag(args, agent, config_manager)

    if cmd == "quiz":
        return handle_quiz(args, agent, config_manager)

    if cmd == "session":
        if args:
            sub = args[0].lower()
            if sub == "chat":
                return handle_session_chat(agent.session)
            if sub == "summary":
                return handle_session_summary(agent.session)
            if sub == "api":
                return handle_session_api(agent.session)
        return "Usage: session chat | session summary | session api"

    return f"Unknown command: '{cmd}'. Type 'help' for available commands."


# ── Helpers ───────────────────────────────────────────────────────────────────


# Parameters that pin to a thread: once the thread has messages they can no
# longer be changed (the choice would invalidate the existing history). Each
# maps to the noun used in the error message.
_LOCKED_WHEN_NONEMPTY: dict[str, str] = {
    "context_strategy": "context_strategy",
    "model": "model",
}


def _changed_keys(sub: str, args: list[str]) -> set[str]:
    """Return the config keys a 'set'/'update' command would change."""
    if sub == "set":
        return {args[0].lower()} if args else set()
    if sub == "update":
        return {a.split("=", 1)[0].strip().lower() for a in args if "=" in a}
    return set()


def _locked_param_error(sub: str, args: list[str], agent: JarvisAgent) -> str | None:
    """Return an error message if the command changes a locked param on a non-empty thread."""
    if not agent.history:
        return None
    for key in _changed_keys(sub, args):
        noun = _LOCKED_WHEN_NONEMPTY.get(key)
        if noun:
            return (
                f"{noun} can only be changed on an empty thread. "
                "Use 'thread new' or 'thread clear' first."
            )
    return None


def _style_note(line: str) -> str:
    """Style one activity line by its source: the model's intent narration (``SAY:`` →
    💬), an MCP tool call (starts with ``[n]`` → 🔧 cyan), or anything else, i.e. a RAG
    request (📚 magenta)."""
    if line.startswith("SAY: "):
        return f"  {_SAY}💬 {line[5:]}{_RESET}"
    if line.lstrip().startswith("["):
        return f"  {_TOOL}🔧 {line}{_RESET}"
    return f"  {_RAG}📚 {line}{_RESET}"


def _live_notes() -> list[str]:
    """Drain new activity lines (logged by the gateway/agent via jarvis.tools) and style
    them — printed in the moment, above the spinner, as tools/RAG are triggered."""
    from .tool_trace import drain
    return [_style_note(ln) for ln in drain()]


def _drain_live_notes() -> None:
    """Discard buffered notes without printing (clears stale lines before a new turn)."""
    from .tool_trace import drain
    drain()


def _format_answer(answer: str) -> str:
    """The final answer under a distinct bold-cyan label, so it stands out from the
    dim trace above it."""
    return f"{_ANSWER}Answer{_RESET}\n{answer}"


# Spinner frames for the in-progress animation (Braille spinner).
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# Don't draw the spinner for operations that finish almost instantly.
_SPINNER_DELAY_S = 0.25


def _run_with_spinner(
    fn: Callable[[], str],
    status_fn: Callable[[], str] | None = None,
    note_fn: Callable[[], list[str]] | None = None,
) -> tuple[object, bool]:
    """Run fn() on a worker thread while animating an elapsed-time spinner.

    Returns (value, interrupted). On Ctrl+C the current step is allowed to finish
    (so its state is saved cleanly) and interrupted=True is returned, letting the
    caller stop before the next step. status_fn supplies a live suffix re-read on
    every frame. note_fn (when given) returns new lines to print *above* the spinner as
    they occur — used to surface tool/RAG notes in the moment. fn's exception, if any,
    is re-raised.
    """
    box: dict = {}

    def _worker() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # propagate to the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()

    frames = itertools.cycle(_SPINNER_FRAMES)
    start = time.perf_counter()
    drawing = False
    interrupted = False

    def _flush_notes() -> None:
        # Print any new notes on their own lines above the spinner (clear the spinner
        # line first so it doesn't merge with the note).
        if note_fn is None:
            return
        for note in note_fn():
            sys.stdout.write(f"\r\033[K{note}\n")
            sys.stdout.flush()

    while worker.is_alive():
        try:
            _flush_notes()
            elapsed = time.perf_counter() - start
            if elapsed >= _SPINNER_DELAY_S:
                drawing = True
                if interrupted:
                    label, tail = "Stopping", "finishing current step…"
                else:
                    label, tail = "Working…", "(Ctrl+C to stop)"
                    if status_fn is not None and (live := status_fn()):
                        tail = f"{live}  ·  {tail}"
                # \033[K clears to end-of-line so a shrinking suffix leaves no residue.
                sys.stdout.write(f"\r{next(frames)} {label} {elapsed:4.1f}s  ·  {tail}\033[K")
                sys.stdout.flush()
            worker.join(0.1)
        except KeyboardInterrupt:
            # Let the in-flight step complete and persist; stop before the next one.
            interrupted = True
    if drawing:
        # Erase the spinner line so it doesn't linger above the output.
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
    _flush_notes()  # any notes that landed on the final tick

    if "error" in box:
        raise box["error"]
    return box.get("value"), interrupted


# ── Banner ────────────────────────────────────────────────────────────────────


def _banner() -> str:
    return (
        "╔══════════════════════════════════════╗\n"
        "║          J A R V I S  v2.0           ║\n"
        "║       Conversational AI Agent        ║\n"
        "╚══════════════════════════════════════╝"
    )
