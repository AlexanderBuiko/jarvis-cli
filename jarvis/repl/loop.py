"""
REPL loop.

Reads user input via InputController and routes it by input type:
  "prompt"  → message forwarded to JarvisAgent
  "command" → text dispatched to command handlers

All conversation and LLM logic lives in the agent; this module is pure UI.
"""

import itertools
import shutil
import sys
import threading
import time
from typing import Callable

from .commands import (
    handle_help,
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
    handle_session_chat,
    handle_session_summary,
    handle_session_api,
    handle_task_show,
    handle_task_new,
    handle_task_list,
    handle_task_start,
    handle_task_pause,
    handle_task_delete,
    handle_task_done,
    handle_task_todo,
    handle_memory_list,
    handle_memory_init,
    handle_memory_edit,
    handle_memory_show,
    handle_memory_load,
    handle_memory_unload,
    handle_memory_write,
    handle_memory_append,
    handle_memory_delete,
    handle_personalize,
    render_plan_progress,
)
from .input import InputController
from ..agent import JarvisAgent
from ..config.manager import ConfigManager
from ..openrouter.client import DEFAULT_MODEL
from ..pipeline.base import GATE_APPROVAL, GATE_QUESTION


def run_repl(agent: JarvisAgent, config_manager: ConfigManager) -> None:
    print(_banner())
    print("Starts in prompt mode (>). Type ! on an empty line to switch modes.\n")

    def _status_fn() -> str:
        tokens = agent.last_context_tokens
        model = config_manager.runtime.get("model") or DEFAULT_MODEL
        ctx = agent.get_context_window(model)
        if ctx:
            pct = round(tokens * 100 / ctx)
            return f"{tokens:,}/{ctx:,} ({pct}%) tokens"
        return f"{tokens:,} tokens"

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
                try:
                    reply, _ = _run_with_spinner(lambda: agent.chat(raw))
                    output = f"A: {reply}"
                except Exception as exc:
                    output = f"Error: {exc}"

        if output:
            print(output)
            print()


# ── Interactive task driver ─────────────────────────────────────────────────────

# Safety cap on driver iterations (a misbehaving model can't loop forever).
_MAX_DRIVE_TURNS = 80

# ANSI colours for the live step table, by status glyph.
_STEP_ANSI = {"✓": "\033[32m", "▶": "\033[33m", "○": "\033[90m"}
_ANSI_RESET = "\033[0m"


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

        # Done stage: the step output is the assembled deliverable — save + report.
        if agent.active_task and agent.active_task["stage"] == "done":
            path = agent.save_task_result(result.text)
            print(f"[done]\n{result.text}\n")
            return f"✓ Task complete. Result saved to {path}"

        header = f"[{result.stage}]"
        if result.advanced_to:
            header += f" → {result.advanced_to}"
        print(f"{header}\n{result.text}\n")

        if interrupted:
            return "■ Stopped. The last completed step is saved — run 'task run' to resume."

        verdict = result.verdict
        if verdict and verdict.gate == GATE_APPROVAL:
            title, options = _approval_prompt(result.stage)
            choice = controller.select(title, options)
            if choice == 0:
                print(f"{title}  →  Confirmed\n")  # replaces the erased arrow menu
                agent.advance_to(verdict.confirm_target)
                continue
            if choice == 1:
                print(f"{title}  →  Rejected\n")
                problem = controller.read_text("What's the problem?")
                agent.advance_to(verdict.reject_target)
                pending = (
                    f"The user rejected this and asked for changes: {problem}\nRevise accordingly."
                    if problem else "The user rejected this; please revise."
                )
                continue
            print(f"{title}  →  (cancelled)\n")
            return "Paused. Run 'task run' to resume."

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


def _approval_prompt(stage: str) -> tuple[str, list[str]]:
    """Title and (Confirm, Reject) labels for an approval gate, made explicit."""
    if stage == "planning":
        return (
            "Approve this plan?",
            ["Confirm — start execution", "Reject — revise the plan"],
        )
    if stage == "validation":
        return (
            "Validation complete — finish the task?",
            ["Confirm — mark done", "Reject — send back to execution"],
        )
    return ("Proceed?", ["Confirm", "Reject"])


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
        return handle_help()

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
            model = config_manager.runtime.get("model") or DEFAULT_MODEL
            ctx = agent.get_context_window(model)
            return handle_thread_summary(agent, ctx)
        return "Usage: thread | thread clear | thread load [<name-or-id>] | thread new [name] | thread rename <name> | thread delete <name-or-id> | thread summary"

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
        if sub == "pause":
            return handle_task_pause(agent)
        if sub == "delete":
            return handle_task_delete(args[1:], agent)
        if sub == "done":
            return handle_task_done(args[1:], agent)
        if sub == "todo":
            return handle_task_todo(args[1:], agent)
        return (
            "Usage: task | task new [name] | task list | task start <name-or-id> | task run | "
            "task pause | task delete <name-or-id> | task done <item> | task todo <item>"
        )

    if cmd == "memory":
        if not args:
            return handle_memory_list(agent)
        sub = args[0].lower()
        if sub == "list":
            return handle_memory_list(agent)
        if sub == "init":
            return handle_memory_init(agent)
        if sub == "edit":
            return handle_memory_edit(args[1:], agent)
        if sub == "show":
            return handle_memory_show(args[1:], agent)
        if sub == "load":
            return handle_memory_load(args[1:], agent)
        if sub == "unload":
            return handle_memory_unload(args[1:], agent)
        if sub == "write":
            return handle_memory_write(args[1:], agent)
        if sub == "append":
            return handle_memory_append(args[1:], agent)
        if sub == "delete":
            return handle_memory_delete(args[1:], agent)
        return "Usage: memory | memory init | memory edit <name> | memory show <name> | memory load <name> | memory unload <name> | memory write <name> <text> | memory append <name> <text> | memory delete <name>"

    if cmd == "personalize":
        return handle_personalize(agent)

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


# Spinner frames for the in-progress animation (Braille spinner).
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# Don't draw the spinner for operations that finish almost instantly.
_SPINNER_DELAY_S = 0.25


def _run_with_spinner(
    fn: Callable[[], str], status_fn: Callable[[], str] | None = None
) -> tuple[object, bool]:
    """Run fn() on a worker thread while animating an elapsed-time spinner.

    Returns (value, interrupted). On Ctrl+C the current step is allowed to finish
    (so its state is saved cleanly) and interrupted=True is returned, letting the
    caller stop before the next step. status_fn supplies a live suffix re-read on
    every frame. fn's exception, if any, is re-raised.
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
    while worker.is_alive():
        try:
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
