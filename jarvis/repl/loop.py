"""
REPL loop.

Reads user input, dispatches built-in commands, and forwards everything
else to JarvisAgent. All conversation and LLM logic lives in the agent;
this module is pure UI.
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
    handle_session_chat,
    handle_session_summary,
    handle_session_api,
)
from ..agent import JarvisAgent
from ..config.manager import ConfigManager

PROMPT = "jarvis> "


def run_repl(agent: JarvisAgent, config_manager: ConfigManager) -> None:
    print(_banner())
    print("Type 'help' for available commands.\n")

    while True:
        try:
            raw = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            sys.exit(0)

        if not raw:
            continue

        output = _dispatch(raw, agent, config_manager)
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
        if args[0].lower() == "clear":
            return handle_history_clear(agent)
        return "Usage: history | history clear"

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

    # Anything else is a message to the agent.
    try:
        return f"A: {agent.chat(raw)}"
    except Exception as exc:
        return f"Error: {exc}"


# ── Banner ────────────────────────────────────────────────────────────────────


def _banner() -> str:
    return (
        "╔══════════════════════════════════════╗\n"
        "║          J A R V I S  v2.0           ║\n"
        "║       Conversational AI Agent        ║\n"
        "╚══════════════════════════════════════╝"
    )
