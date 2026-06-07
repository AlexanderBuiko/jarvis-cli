"""
Main REPL loop.

Reads user input, dispatches to command handlers or to the LLM interaction
flow (including the clarification question loop).
"""

import sys
from typing import Any

from .commands import (
    handle_help,
    handle_config_show,
    handle_config_set,
    handle_config_update,
    handle_config_reset,
    handle_mode_show,
    handle_mode_set,
    handle_session_results,
)
from ..config.manager import ConfigManager
from ..openrouter.client import OpenRouterClient, Completion
from ..prompt_builder.builder import (
    build_system_prompt,
    build_clarification_prompt,
    build_final_prompt,
    build_strategy_prompt,
    build_prompt_generation_request,
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

    if cmd in ("exit", "quit"):
        print("Goodbye.")
        sys.exit(0)

    if cmd == "help":
        return handle_help()

    if cmd == "mode":
        if not args:
            return handle_mode_show(config_manager)
        return handle_mode_set(args[0].lower(), config_manager)

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

    if cmd == "session":
        if args and args[0].lower() == "results":
            return handle_session_results(session_store)
        return "Usage: session results"

    return _handle_llm_request(raw, config_manager, client, session_store)


# ── LLM interaction ───────────────────────────────────────────────────────────


def _handle_llm_request(
    user_request: str,
    config_manager: ConfigManager,
    client: OpenRouterClient,
    session_store: SessionStore,
) -> str:
    params = config_manager.runtime
    system_prompt = build_system_prompt(params)
    clarifications: list[tuple[str, str]] = []

    # Ordered log of every OpenRouter call made during this interaction.
    api_calls: list[dict] = []

    # ── Clarification loop ────────────────────────────────────────────────────
    total_clarifications = params.get("clarification_questions", 0)
    for q_num in range(1, total_clarifications + 1):
        clarify_instruction = build_clarification_prompt(params, q_num)

        messages = _build_messages(
            system_prompt=system_prompt,
            user_request=user_request,
            clarifications=clarifications,
            extra_instruction=clarify_instruction,
        )

        try:
            c = client.complete(messages, params)
        except Exception as exc:
            return f"API error: {exc}"

        api_calls.append(_make_call_record(
            index=len(api_calls) + 1,
            label=f"clarification_round_{q_num}_of_{total_clarifications}",
            completion=c,
        ))

        print(f"\nA: {c.text.strip()}\n")

        try:
            user_answer = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            sys.exit(0)

        clarifications.append((c.text.strip(), user_answer))

    # ── Final answer ──────────────────────────────────────────────────────────
    base_message = build_final_prompt(user_request, clarifications)
    generated_prompt: str | None = None

    if params.get("solution_strategy") == "prompt_generation":
        stage1_messages = _build_messages(
            system_prompt=system_prompt,
            user_request=build_prompt_generation_request(base_message),
            clarifications=[],
            extra_instruction=None,
        )
        try:
            stage1 = client.complete(stage1_messages, {})
        except Exception as exc:
            return f"API error (prompt generation stage): {exc}"

        generated_prompt = stage1.text.strip()
        api_calls.append(_make_call_record(
            index=len(api_calls) + 1,
            label="prompt_generation_stage1",
            completion=stage1,
        ))
        final_user_message = generated_prompt
    else:
        final_user_message = build_strategy_prompt(params, base_message)

    messages = _build_messages(
        system_prompt=system_prompt,
        user_request=final_user_message,
        clarifications=[],
        extra_instruction=None,
    )

    try:
        completion = client.complete(messages, params)
    except Exception as exc:
        return f"API error: {exc}"

    api_calls.append(_make_call_record(
        index=len(api_calls) + 1,
        label="final_answer",
        completion=completion,
    ))

    display_response = completion.text.strip()
    stop_seq = params.get("stop_sequence", "")
    if params.get("prompt_stop_enabled") and stop_seq and display_response.endswith(stop_seq):
        display_response = display_response[: -len(stop_seq)].rstrip()

    session_store.add(
        original_request=user_request,
        config_snapshot=dict(params),
        final_response=display_response,
        finish_reason=completion.finish_reason,
        api_calls=api_calls,
        generated_prompt=generated_prompt,
        clarifications=clarifications,
    )

    return f"A: {display_response}"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_call_record(index: int, label: str, completion: Completion) -> dict:
    """Build one entry for the api_calls trace list."""
    raw_resp = completion.response
    choice = raw_resp.get("choices", [{}])[0] if raw_resp else {}
    return {
        "index": index,
        "label": label,
        "request": completion.request,
        "response": {
            "content": completion.text,
            "finish_reason": completion.finish_reason,
            "usage": raw_resp.get("usage"),
            "model": raw_resp.get("model"),
            "id": raw_resp.get("id"),
        },
    }


def _build_messages(
    system_prompt: str,
    user_request: str,
    clarifications: list[tuple[str, str]],
    extra_instruction: str | None,
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    if clarifications:
        messages.append({"role": "user", "content": user_request})
        for question, answer in clarifications:
            messages.append({"role": "assistant", "content": question})
            messages.append({"role": "user", "content": answer})
    else:
        content = user_request
        if extra_instruction:
            content = f"{extra_instruction}\n\nUser request: {user_request}"
        messages.append({"role": "user", "content": content})

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
