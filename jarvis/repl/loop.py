"""
REPL loop.

Reads user input via InputController and routes it by input type:
  "prompt"  → message forwarded to JarvisAgent
  "command" → text dispatched to command handlers

All conversation and LLM logic lives in the agent; this module is pure UI.
"""

import sys

from .commands import (
    handle_help,
    handle_config_show,
    handle_config_set,
    handle_config_update,
    handle_config_reset,
    handle_history_show,
    handle_history_clear,
    handle_history_load,
    handle_history_new,
    handle_history_rename,
    handle_history_delete,
    handle_session_chat,
    handle_session_summary,
    handle_session_api,
)
from .input import InputController
from ..agent import JarvisAgent
from ..config.manager import ConfigManager


def run_repl(agent: JarvisAgent, config_manager: ConfigManager) -> None:
    print(_banner())
    print("Starts in prompt mode (>). Type ! on an empty line to switch modes.\n")

    controller = InputController()

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
                output = f"A: {agent.chat(raw)}"
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
            return handle_config_set(args[1:], config_manager)
        if sub == "reset":
            return handle_config_reset(config_manager)
        if sub == "update":
            return handle_config_update(args[1:], config_manager)
        return f"Unknown config sub-command: '{sub}'"

    if cmd == "history":
        if not args:
            return handle_history_show(agent)
        sub = args[0].lower()
        if sub == "clear":
            return handle_history_clear(agent)
        if sub == "load":
            return handle_history_load(args[1:], agent)
        if sub == "new":
            return handle_history_new(args[1:], agent)
        if sub == "rename":
            return handle_history_rename(args[1:], agent)
        if sub == "delete":
            return handle_history_delete(args[1:], agent)
        return "Usage: history | history clear | history load [<name-or-id>] | history new [name] | history rename <name> | history delete <name-or-id>"

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


# ── Banner ────────────────────────────────────────────────────────────────────


def _banner() -> str:
    return (
        "╔══════════════════════════════════════╗\n"
        "║          J A R V I S  v2.0           ║\n"
        "║       Conversational AI Agent        ║\n"
        "╚══════════════════════════════════════╝"
    )
