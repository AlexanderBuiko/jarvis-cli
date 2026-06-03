"""
Main REPL loop.

Reads user input, dispatches to command handlers or to the LLM interaction
flow (including the clarification question loop).
"""

import sys

from .commands import (
    handle_help,
    handle_config_show,
    handle_config_set,
    handle_config_reset,
    handle_session_results,
)
from ..config.manager import ConfigManager
from ..openrouter.client import OpenRouterClient
from ..prompt_builder.builder import (
    build_system_prompt,
    build_clarification_prompt,
    build_final_prompt,
)
from ..session.store import SessionStore

PROMPT = "jarvis> "


def run_repl(config_manager: ConfigManager, client: OpenRouterClient) -> None:
    session_store = SessionStore()
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

        output = _dispatch(raw, config_manager, client, session_store)
        if output:
            print(output)
            print()


# ── Dispatcher ────────────────────────────────────────────────────────────────


def _dispatch(
    raw: str,
    config_manager: ConfigManager,
    client: OpenRouterClient,
    session_store: SessionStore,
) -> str:
    tokens = raw.split()
    cmd = tokens[0].lower()
    args = tokens[1:]

    # Built-in commands
    if cmd in ("exit", "quit"):
        print("Goodbye.")
        sys.exit(0)

    if cmd == "help":
        return handle_help()

    if cmd == "config":
        if not args:
            return "Usage: config show | config set <key> <value> | config reset"
        sub = args[0].lower()
        if sub == "show":
            return handle_config_show(config_manager)
        if sub == "set":
            return handle_config_set(args[1:], config_manager)
        if sub == "reset":
            return handle_config_reset(config_manager)
        return f"Unknown config sub-command: '{sub}'"

    if cmd == "session":
        if args and args[0].lower() == "results":
            return handle_session_results(session_store)
        return "Usage: session results"

    # Anything else is treated as a question/request to the LLM
    return _handle_llm_request(raw, config_manager, client, session_store)


# ── LLM interaction (including clarification loop) ────────────────────────────


def _handle_llm_request(
    user_request: str,
    config_manager: ConfigManager,
    client: OpenRouterClient,
    session_store: SessionStore,
) -> str:
    cfg = config_manager.current
    system_prompt = build_system_prompt(cfg)
    clarifications: list[tuple[str, str]] = []

    # ── Clarification loop ────────────────────────────────────────────────────
    for q_num in range(1, cfg.clarification_questions + 1):
        clarify_instruction = build_clarification_prompt(cfg, q_num)

        messages = _build_messages(
            system_prompt=system_prompt,
            user_request=user_request,
            clarifications=clarifications,
            extra_instruction=clarify_instruction,
        )

        try:
            question, _ = client.complete(messages, cfg)
        except Exception as exc:
            return f"API error: {exc}"

        print(f"\nA: {question.strip()}\n")

        try:
            user_answer = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            sys.exit(0)

        clarifications.append((question.strip(), user_answer))

    # ── Final answer ──────────────────────────────────────────────────────────
    final_user_message = build_final_prompt(cfg, user_request, clarifications)

    messages = _build_messages(
        system_prompt=system_prompt,
        user_request=final_user_message,
        clarifications=[],  # already embedded in final_user_message
        extra_instruction=None,
    )

    try:
        response, finish_reason = client.complete(messages, cfg)
    except Exception as exc:
        return f"API error: {exc}"

    # Strip the stop marker from the displayed output (if present)
    display_response = response.strip()
    if cfg.prompt_stop_enabled and display_response.endswith(cfg.stop_sequence):
        display_response = display_response[: -len(cfg.stop_sequence)].rstrip()

    session_store.add(
        original_request=user_request,
        cfg=cfg,
        final_response=display_response,
        finish_reason=finish_reason,
        clarifications=clarifications,
    )

    return f"A: {display_response}"


def _build_messages(
    system_prompt: str,
    user_request: str,
    clarifications: list[tuple[str, str]],
    extra_instruction: str | None,
) -> list[dict]:
    """
    Build the messages list for the API call.

    clarifications is used when we want to replay Q&A as multi-turn history
    (only during the clarification loop itself, not for the final call where
    everything is folded into one user message).
    """
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # Replay clarification history as alternating turns
    if clarifications:
        # First user turn is the original request
        messages.append({"role": "user", "content": user_request})
        for question, answer in clarifications:
            messages.append({"role": "assistant", "content": question})
            messages.append({"role": "user", "content": answer})
    else:
        content = user_request
        if extra_instruction:
            content = f"{extra_instruction}\n\nUser request: {user_request}"
        messages.append({"role": "user", "content": content})

    # Attach the extra instruction when in clarification loop with history
    if clarifications and extra_instruction:
        messages.append({"role": "user", "content": extra_instruction})

    return messages


def _banner() -> str:
    return (
        "╔══════════════════════════════════════╗\n"
        "║          J A R V I S  v1.0           ║\n"
        "║  LLM Controls & Formatting Explorer  ║\n"
        "╚══════════════════════════════════════╝"
    )
