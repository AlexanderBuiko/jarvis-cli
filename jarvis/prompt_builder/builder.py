"""
Prompt construction for JarvisAgent.

Builds the system prompt from the active configuration and wraps user messages
with strategy-specific instructions when a solution strategy is set.
"""

from typing import Any


_BASE_SYSTEM_PROMPT = """\
You are Jarvis, an AI agent.

Your responsibility is to process user requests and provide useful, accurate responses.

If information is missing, ask clarifying questions.

Be concise unless the user requests detailed explanations."""

_STEP_BY_STEP_INSTRUCTION = (
    "Think through this problem step by step. "
    "Show your reasoning clearly before stating your final answer."
)

_EXPERT_PANEL_INSTRUCTION = (
    "You are facilitating a panel of three domain experts with different perspectives. "
    "Present each expert's view briefly, then synthesise a final answer that integrates "
    "the strongest points from all perspectives."
)


def build_system_prompt(params: dict[str, Any]) -> str:
    """Return the system prompt for the current configuration.

    step_by_step and expert_panel strategies append additional instructions
    to the base agent prompt.
    """
    parts = [_BASE_SYSTEM_PROMPT]

    strategy = params.get("solution_strategy", "direct")
    if strategy == "step_by_step":
        parts.append(_STEP_BY_STEP_INSTRUCTION)
    elif strategy == "expert_panel":
        parts.append(_EXPERT_PANEL_INSTRUCTION)

    return "\n\n".join(parts)


def build_strategy_prompt(params: dict[str, Any], user_request: str) -> str:
    """Wrap the user request with strategy-specific instructions for the user turn.

    step_by_step and expert_panel add framing to both the system prompt and
    the user turn. direct and prompt_generation pass the request through unchanged.
    """
    strategy = params.get("solution_strategy", "direct")

    if strategy == "step_by_step":
        return (
            "Solve the problem step by step.\n"
            "Show your reasoning clearly.\n"
            "Provide the final answer separately.\n\n"
            f"{user_request}"
        )

    if strategy == "expert_panel":
        return (
            "You are a panel of three experts:\n"
            "  - Expert 1 (Analyst): analyse the problem thoroughly.\n"
            "  - Expert 2 (Engineer): propose a concrete solution.\n"
            "  - Expert 3 (Critic): challenge assumptions and improve the answer.\n\n"
            "Each expert addresses the problem independently.\n"
            "Then provide a consolidated final answer.\n\n"
            f"{user_request}"
        )

    return user_request


def build_summary_prompt(existing_summary: str | None, new_messages: list[dict]) -> str:
    """Build the prompt used to update the rolling conversation summary.

    Instructs the model to preserve concrete facts (names, numbers, decisions,
    code snippets) so that summary drift stays minimal across compression cycles.
    """
    parts: list[str] = []

    if existing_summary:
        parts.append(
            f"Existing conversation summary (covers earlier turns):\n{existing_summary}"
        )

    parts.append("New conversation turns to incorporate into the summary:")
    for msg in new_messages:
        label = "User" if msg["role"] == "user" else "Assistant"
        parts.append(f"{label}: {msg['content']}")

    parts.append(
        "Produce an updated summary that covers all turns shown above.\n"
        "Preservation rules — you MUST retain all of the following verbatim or with full precision:\n"
        "  • Specific names, identifiers, file paths, URLs\n"
        "  • Numbers, measurements, dates, version strings\n"
        "  • Code snippets, commands, configuration values\n"
        "  • Decisions made and their stated reasons\n"
        "  • Errors, failures, and how they were resolved\n"
        "  • Any information the user explicitly marked as important\n"
        "Write in third person. Be concise but complete. Output only the summary text, no preamble."
    )

    return "\n\n".join(parts)


def build_prompt_generation_request(user_request: str) -> str:
    """Stage-1 message for the prompt_generation strategy.

    Asks the model to produce the most effective prompt for the task.
    The generated prompt is used as the user message in the stage-2 request.
    """
    return (
        "Create the most effective prompt that would help an AI solve the "
        "following task accurately.\n\n"
        f"Task:\n{user_request}\n\n"
        "Output only the prompt itself, with no explanation or commentary."
    )
