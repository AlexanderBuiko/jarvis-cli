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
  mode                    Show available modes and which is active
  mode <name>             Switch to an assignment mode (replaces config entirely)
  config show             Show active mode and its current parameters
  config set <key> <val>  Change a parameter (key must exist in the active mode)
  config update <k=v> …   Change multiple parameters at once
  config reset            Restore the active mode's preset defaults
  session results         Show all interactions from this session (default view)
  session results --api   Show API request/response payloads
  session results --benchmark  Show API payloads + benchmark metrics
  exit / quit             Exit Jarvis

Assignment modes
────────────────
  basic            Only model + messages are sent (no extra parameters)
  response_control Response format, length, and stop sequence experiments
  prompting        Prompting strategy experiments
  temperature      Temperature-only experiments

Parameters per mode
───────────────────
  basic            (none)

  temperature
    temperature    Sampling temperature (0.0 – 2.0)

  response_control
    max_tokens           Maximum tokens in the response
    response_format      plain | bullet_list | numbered_list
    max_words            Maximum words in the response (prompt-level)
    prompt_stop_enabled  true | false — inject stop marker in system prompt
    api_stop_enabled     true | false — send stop sequence to API
    stop_sequence        The stop string (default: ###END###)

  prompting
    solution_strategy    direct | step_by_step | prompt_generation | expert_panel

Complete parameter reference
───────────────────────────
The following parameters exist in the system.  Each is available only when
the active mode's preset includes it.  They are listed here for reference
independent of any specific mode.

  Model selection
    model          str                OpenRouter model identifier (e.g. anthropic/claude-sonnet-4)

  Sampling (sent to OpenRouter API)
    temperature    float  0.0 – 2.0   Sampling temperature
    top_p          float  0.0 – 1.0   Nucleus sampling probability
    top_k          int                Top-k sampling cutoff
    max_tokens     int                Maximum tokens in the response
    seed           int | none         Random seed for reproducibility

  Stop sequences
    api_stop_enabled    bool    Send stop sequence to OpenRouter API
    prompt_stop_enabled bool    Inject stop marker into system prompt
    stop_sequence       str     The stop string (default: ###END###)

  Response formatting (prompt-level)
    response_format  plain | bullet_list | numbered_list
    max_words        int   Maximum words in the response

  Prompting strategies
    solution_strategy  direct | step_by_step | prompt_generation | expert_panel

  Clarification loop
    clarification_questions  int  (default: 0)

      Controls how many clarification rounds the model is allowed before
      giving its final answer.

        0   — no clarification loop; model answers immediately (default)
        1+  — model asks one clarification question per round, waits for
               the user's answer, then proceeds to the next round or final answer

      Important: this does NOT guarantee the model will ask questions.
      It only limits how many clarification iterations are allowed.
      Each round produces a separate logged OpenRouter call visible in
      'session results'.

Examples
────────
  mode basic
  mode temperature
  config set temperature 1.2
  mode response_control
  config set response_format bullet_list
  config update max_words=50 api_stop_enabled=true
  mode prompting
  config set solution_strategy expert_panel
  config reset
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


def handle_config_update(args: list[str], config_manager: ConfigManager) -> str:
    if not args:
        return "Usage: config update <key=value> [<key=value> ...]"
    try:
        result = config_manager.update(args)
        return f"Updated:\n{result}"
    except (ValueError, TypeError) as exc:
        return f"Error: {exc}"


def handle_config_reset(config_manager: ConfigManager) -> str:
    config_manager.reset()
    return f"Configuration reset to '{config_manager.active_mode}' preset defaults."


def handle_mode_show(config_manager: ConfigManager) -> str:
    return config_manager.show_modes()


def handle_mode_set(name: str, config_manager: ConfigManager) -> str:
    try:
        return config_manager.set_mode(name)
    except ValueError as exc:
        return f"Error: {exc}"


def handle_session_results(
    session_store: SessionStore,
    flags: set[str] | None = None,
) -> str:
    flags = flags or set()
    if "--benchmark" in flags:
        return session_store.format_results(mode="benchmark")
    if "--api" in flags:
        return session_store.format_results(mode="api")
    return session_store.format_results(mode="default")
