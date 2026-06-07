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
from ..openrouter.client import OpenRouterClient, Completion, DEFAULT_MODEL
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
            flags = set(args[1:])
            return handle_session_results(session_store, flags)
        return "Usage: session results [--api | --benchmark]"

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
            client=client,
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
        # Pass model so the configured model is used even with empty API params.
        stage1_params = {"model": params["model"]} if "model" in params else {}
        try:
            stage1 = client.complete(stage1_messages, stage1_params)
        except Exception as exc:
            return f"API error (prompt generation stage): {exc}"

        generated_prompt = stage1.text.strip()
        api_calls.append(_make_call_record(
            index=len(api_calls) + 1,
            label="prompt_generation_stage1",
            completion=stage1,
            client=client,
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
        client=client,
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


def _make_call_record(
    index: int,
    label: str,
    completion: Completion,
    client: "OpenRouterClient",
) -> dict:
    """Build one entry for the api_calls trace list, including benchmark metrics."""
    raw_resp = completion.response
    # requested_model: what we explicitly sent to OpenRouter.
    # actual_model: what OpenRouter reports in the response (may be a versioned
    #   variant such as "qwen/qwen3-32b-04-28" for a request of "qwen/qwen3-32b").
    requested_model: str = completion.request.get("model") or DEFAULT_MODEL
    actual_model: str = raw_resp.get("model") or requested_model

    usage = raw_resp.get("usage") or {}
    prompt_tokens: int | None = usage.get("prompt_tokens")
    completion_tokens: int | None = usage.get("completion_tokens")
    total_tokens: int | None = usage.get("total_tokens")

    # Pricing priority: requested_model first (canonical, present in the catalog),
    # fall back to actual_model only if the requested identifier has no entry.
    input_per_m, output_per_m = client.get_pricing(requested_model)
    if input_per_m is None and actual_model != requested_model:
        input_per_m, output_per_m = client.get_pricing(actual_model)

    if prompt_tokens is not None and input_per_m is not None:
        input_cost_usd: float | None = (prompt_tokens / 1_000_000) * input_per_m
    else:
        input_cost_usd = None

    if completion_tokens is not None and output_per_m is not None:
        output_cost_usd: float | None = (completion_tokens / 1_000_000) * output_per_m
    else:
        output_cost_usd = None

    total_cost_usd: float | None = (
        input_cost_usd + output_cost_usd
        if input_cost_usd is not None and output_cost_usd is not None
        else None
    )

    return {
        "index": index,
        "label": label,
        "request": completion.request,
        "response": {
            "content": completion.text,
            "finish_reason": completion.finish_reason,
            "usage": usage or None,
            "model": actual_model,
            "id": raw_resp.get("id"),
        },
        "benchmark": {
            "requested_model": requested_model,
            "actual_model": actual_model,
            "latency_ms": round(completion.latency_ms, 2),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "input_cost_usd": input_cost_usd,
            "output_cost_usd": output_cost_usd,
            "total_cost_usd": total_cost_usd,
            "finish_reason": completion.finish_reason,
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
