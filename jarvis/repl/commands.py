"""
REPL command handlers.

Each handler receives parsed arguments and shared application state, and
returns a string to print. No I/O is performed here.
"""

from ..agent import JarvisAgent
from ..config.manager import ConfigManager
from ..session.store import SessionStore

HELP_TEXT = """
Jarvis — conversational AI agent

Modes
─────
  >   Prompt mode  — input is sent to the agent
  !   Command mode — input is dispatched to the REPL

  Type ! on an empty line to toggle between modes.
  History (↑/↓ on empty line)
  Autocomplete (↑/↓/Tab in command mode when suggestions are visible)

Commands
────────
  help                    Show this help message
  config show             Show active configuration parameters
  config set <key> <val>  Set a parameter
  config update <k=v> …   Set multiple parameters at once
  config reset            Clear all parameters (revert to API defaults)
  history                 Show the current conversation context
  history clear           Clear conversation history
  session chat            Show the full conversation transcript
  session summary         Show aggregate session statistics
  session api             Show raw API request/response payloads
  exit / quit             Exit Jarvis

Parameters
──────────
  model              str   OpenRouter model identifier
                           Default: anthropic/claude-sonnet-4
                           Example: config set model anthropic/claude-haiku-3

  temperature        float  0.0 – 2.0   Sampling temperature
  top_p              float  0.0 – 1.0   Nucleus sampling probability
  top_k              int                Top-k sampling cutoff
  max_tokens         int                Maximum tokens in the response
  seed               int | none         Random seed for reproducibility

  solution_strategy  direct | step_by_step | prompt_generation | expert_panel
                           Controls how the agent approaches the problem.
                             direct            — answer immediately (default)
                             step_by_step      — reason through steps explicitly
                             expert_panel      — three-expert panel with synthesis
                             prompt_generation — stage 1: generate an optimised
                                                 prompt; stage 2: answer with it

Examples
────────
  config set model anthropic/claude-haiku-3
  config set temperature 0.8
  config set solution_strategy step_by_step
  config update temperature=0.5 max_tokens=500
  config reset
  history
  history clear
  session chat
  session summary
  session api
"""


def handle_help() -> str:
    return HELP_TEXT


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
    return "Configuration cleared. Using API defaults."


def handle_history_show(agent: JarvisAgent) -> str:
    """Show what the agent currently holds as conversation context."""
    history = agent.history
    if not history:
        return "Conversation history is empty."
    turn_count = len(history) // 2
    lines = [f"Conversation context ({turn_count} turn(s))", ""]
    sep = "·" * 40
    turn = 0
    for i in range(0, len(history), 2):
        turn += 1
        user_msg = history[i]["content"]
        assistant_msg = (
            history[i + 1]["content"] if i + 1 < len(history) else "(no response)"
        )
        lines += [
            sep,
            f"  [{turn}] You   : {user_msg}",
            f"  [{turn}] Jarvis: {assistant_msg}",
        ]
    lines.append(sep)
    return "\n".join(lines)


def handle_history_clear(agent: JarvisAgent) -> str:
    agent.reset_history()
    return "Conversation history cleared."


def handle_session_chat(session_store: SessionStore) -> str:
    return session_store.format_chat()


def handle_session_summary(session_store: SessionStore) -> str:
    return session_store.format_summary()


def handle_session_api(session_store: SessionStore) -> str:
    return session_store.format_api()
