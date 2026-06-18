"""
REPL loop.

Reads user input via InputController and routes it by input type:
  "prompt"  → message forwarded to JarvisAgent
  "command" → text dispatched to command handlers

All conversation and LLM logic lives in the agent; this module is pure UI.
"""

import itertools
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
    handle_task_run,
    handle_task_next,
    handle_task_back,
    handle_task_replan,
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
)
from .input import InputController
from ..agent import JarvisAgent
from ..config.manager import ConfigManager
from ..openrouter.client import DEFAULT_MODEL


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

    controller = InputController(status_fn=_status_fn)

    while True:
        try:
            input_type, raw = controller.read_input()
        except EOFError:
            print("\nGoodbye.")
            sys.exit(0)

        if input_type == "command":
            output = _dispatch(raw, agent, config_manager)
        else:
            try:
                output = f"A: {_run_with_spinner(lambda: agent.chat(raw))}"
            except Exception as exc:
                output = f"Error: {exc}"

        if output:
            print(output)
            print()


# ── Dispatcher ────────────────────────────────────────────────────────────────


def _dispatch(
    raw: str,
    agent: JarvisAgent,
    config_manager: ConfigManager,
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
            return _run_with_spinner(lambda: handle_task_run(agent))
        if sub == "next":
            return handle_task_next(agent)
        if sub == "back":
            return handle_task_back(agent)
        if sub == "replan":
            return handle_task_replan(agent)
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
            "task next | task back | task replan | task pause | task delete <name-or-id> | "
            "task done <item> | task todo <item>"
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


def _run_with_spinner(fn: Callable[[], str]) -> str:
    """Run fn() on a worker thread while animating an elapsed-time spinner.

    Signals that work is in progress and that input is not expected. The result
    (or exception) of fn is returned (or re-raised) once it completes.
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
    while worker.is_alive():
        elapsed = time.perf_counter() - start
        if elapsed >= _SPINNER_DELAY_S:
            drawing = True
            sys.stdout.write(f"\r{next(frames)} Working… {elapsed:4.1f}s  (please wait)")
            sys.stdout.flush()
        worker.join(0.1)
    if drawing:
        # Erase the spinner line so it doesn't linger above the output.
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    if "error" in box:
        raise box["error"]
    return box["value"]


# ── Banner ────────────────────────────────────────────────────────────────────


def _banner() -> str:
    return (
        "╔══════════════════════════════════════╗\n"
        "║          J A R V I S  v2.0           ║\n"
        "║       Conversational AI Agent        ║\n"
        "╚══════════════════════════════════════╝"
    )
