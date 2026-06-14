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


def build_topic_routing_prompt(user_message: str, topic_summaries: dict[str, str]) -> str:
    """Build the prompt used to determine which topic a user message belongs to.

    When no topics exist yet, asks the model to create the first topic name.
    When topics exist, asks the model to assign to an existing topic or create a new one.
    Topic names are returned as short kebab-case identifiers.
    """
    if not topic_summaries:
        return (
            "Based on the following message, create a short topic name that describes what is being discussed.\n"
            "Requirements: 2-4 words, kebab-case (e.g. android-architecture, job-search, travel-planning).\n\n"
            f"Message: {user_message}\n\n"
            "Output only the topic name, nothing else."
        )

    parts = ["Existing conversation topics:"]
    for name, summary in topic_summaries.items():
        parts.append(f"  {name}: {summary}")
    parts.append(f"\nNew message: {user_message}")
    parts.append(
        "\nDecide whether this message continues an existing topic or starts a new one.\n"
        "If it continues an existing topic: output that topic's exact name.\n"
        "If it starts a new topic: output a short new topic name (2-4 words, kebab-case).\n"
        "Output only the topic name, nothing else."
    )
    return "\n\n".join(parts)


def build_facts_extraction_prompt(existing_facts: str | None, latest_exchange: list[dict]) -> str:
    """Build the prompt used to update the sticky facts after each turn.

    Instructs the model to maintain a key-value facts list covering goals,
    constraints, preferences, decisions, and agreements from the conversation.
    """
    parts: list[str] = []

    if existing_facts:
        parts.append(f"Current facts:\n{existing_facts}")

    parts.append("Latest exchange to incorporate:")
    for msg in latest_exchange:
        label = "User" if msg["role"] == "user" else "Assistant"
        parts.append(f"{label}: {msg['content']}")

    parts.append(
        "Update the facts list based on the latest exchange.\n"
        "Keep all existing facts that are still valid. Add newly learned facts. Remove facts that are no longer true.\n"
        "Format: one fact per line as 'key: value'.\n"
        "Track facts in these categories: goals, constraints, preferences, decisions, agreements.\n"
        "Output only the updated facts list, no preamble or explanation."
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
