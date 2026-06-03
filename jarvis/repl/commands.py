"""
REPL command handlers.

Each handler receives the parsed arguments (list of strings after the command
keyword) and the shared application state, then returns a string to print.
"""

from ..config.manager import ConfigManager
from ..session.store import SessionStore

HELP_TEXT = """
Jarvis — interactive LLM assistant

Commands
────────
  help                    Show this help message
  config show             Show current configuration
  config set <key> <val>  Change a configuration value
  config reset            Reset all settings to defaults
  session results         Show all interactions from this session
  exit / quit             Exit Jarvis

Asking questions
────────────────
  Just type any question or request and press Enter.
  Jarvis will answer using the current configuration.

Configuration keys
──────────────────
  temperature             Sampling temperature (0.0 – 2.0)
  top_p                   Nucleus sampling probability (0.0 – 1.0)
  top_k                   Top-k sampling
  max_tokens              Maximum tokens in the response
  seed                    Random seed (use 'none' to disable)

  response_format         plain | bullet_list | numbered_list
  max_words               Maximum words in the response (prompt-level)

  clarification_questions Number of clarification questions before answering

  prompt_stop_enabled     true | false — inject stop marker in prompt
  api_stop_enabled        true | false — send stop sequence to API
  stop_sequence           The stop string (default: ###END###)

  control_mode            prompt | api | both

Examples
────────
  config set temperature 0.8
  config set response_format bullet_list
  config set clarification_questions 2
  config set control_mode prompt
  config set prompt_stop_enabled true
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
        confirmation = config_manager.set(key, value)
        return f"Updated: {confirmation}"
    except (ValueError, TypeError) as exc:
        return f"Error: {exc}"


def handle_config_reset(config_manager: ConfigManager) -> str:
    config_manager.reset()
    return "Configuration reset to defaults."


def handle_session_results(session_store: SessionStore) -> str:
    return session_store.format_results()
