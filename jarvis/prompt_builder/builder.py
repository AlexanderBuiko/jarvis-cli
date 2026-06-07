"""
Builds system and user prompts from the active mode's runtime params dict.

All functions accept *params* — the mode's live configuration snapshot.
A key's mere presence in the dict activates the corresponding behaviour;
absence means the feature is off for that mode.
"""

from typing import Any


_FORMAT_INSTRUCTIONS: dict[str, str] = {
    "plain": "Respond in plain prose.",
    "bullet_list": "Format your response as a bullet list.",
    "numbered_list": "Format your response as a numbered list.",
}

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
    """Return the system prompt implied by the active mode's params."""
    lines = ["You are Jarvis, a helpful and concise assistant."]

    # Response format (response_control mode)
    if "response_format" in params:
        instruction = _FORMAT_INSTRUCTIONS.get(params["response_format"], "")
        if instruction:
            lines.append(instruction)

    # Length constraint (response_control mode)
    if "max_words" in params:
        lines.append(f"Keep your response to a maximum of {params['max_words']} words.")

    # Prompt-level stop marker (response_control mode, when enabled)
    if params.get("prompt_stop_enabled") and "stop_sequence" in params:
        lines.append(
            f'When you have finished your response, write exactly '
            f'"{params["stop_sequence"]}" on its own line.'
        )

    # Reasoning strategy (prompting mode)
    if "solution_strategy" in params:
        strategy = params["solution_strategy"]
        if strategy == "step_by_step":
            lines.append(_STEP_BY_STEP_INSTRUCTION)
        elif strategy == "expert_panel":
            lines.append(_EXPERT_PANEL_INSTRUCTION)
        # "direct" and "prompt_generation" add nothing here.
        # "prompt_generation" is handled as a two-phase flow in the REPL loop.

    return "\n".join(lines)


def build_strategy_prompt(params: dict[str, Any], user_request: str) -> str:
    """Wrap *user_request* with strategy-specific instructions for the user turn.

    Only ``step_by_step`` and ``expert_panel`` augment the message here.
    ``direct`` and ``prompt_generation`` pass the request through unchanged
    (``prompt_generation`` phase-2 message is produced by the REPL loop).
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


def build_prompt_generation_request(user_request: str) -> str:
    """Stage-1 message for the ``prompt_generation`` strategy.

    Asks the model to produce the most effective prompt for the task.
    """
    return (
        "Create the most effective prompt that would help an AI solve the "
        "following task accurately.\n\n"
        f"Task:\n{user_request}\n\n"
        "Output only the prompt itself, with no explanation or commentary."
    )


def build_clarification_prompt(params: dict[str, Any], question_number: int) -> str:
    """Return an instruction asking the model for one clarification question."""
    total = params.get("clarification_questions", 0)
    return (
        f"Before answering, ask clarification question {question_number} of "
        f"{total}. Ask only this single question now. "
        "Do not answer the original request yet."
    )


def build_final_prompt(original_request: str, clarifications: list[tuple[str, str]]) -> str:
    """Build the final user message, embedding any collected clarification Q&A."""
    if not clarifications:
        return original_request

    parts = [f"Original request: {original_request}", "", "Clarification answers:"]
    for i, (question, answer) in enumerate(clarifications, start=1):
        parts.append(f"  Q{i}: {question}")
        parts.append(f"  A{i}: {answer}")
    parts.append("")
    parts.append("Now provide the final answer.")
    return "\n".join(parts)
