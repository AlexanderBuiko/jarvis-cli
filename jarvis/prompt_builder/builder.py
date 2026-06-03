"""
Builds system and user prompts dynamically based on active configuration.

Prompt-level controls are injected here as natural-language instructions.
API-level controls are passed separately in the API request (see openrouter/).
"""

from ..config.schema import JarvisConfig


_FORMAT_INSTRUCTIONS = {
    "plain": "Respond in plain prose.",
    "bullet_list": "Format your response as a bullet list.",
    "numbered_list": "Format your response as a numbered list.",
}


def build_system_prompt(cfg: JarvisConfig) -> str:
    """Return a system prompt that encodes all active prompt-level controls."""
    use_prompt_controls = cfg.control_mode in ("prompt", "both")

    lines = ["You are Jarvis, a helpful and concise assistant."]

    if use_prompt_controls:
        # Response format
        fmt_instruction = _FORMAT_INSTRUCTIONS.get(cfg.response_format, "")
        if fmt_instruction:
            lines.append(fmt_instruction)

        # Length constraint
        lines.append(f"Keep your response to a maximum of {cfg.max_words} words.")

        # Explicit stop marker
        if cfg.prompt_stop_enabled:
            lines.append(
                f'When you have finished your response, write exactly "{cfg.stop_sequence}" on its own line.'
            )

    return "\n".join(lines)


def build_clarification_prompt(cfg: JarvisConfig, question_number: int) -> str:
    """
    Return an instruction that tells the model to ask ONE clarification question.

    question_number is 1-based.
    """
    return (
        f"Before answering, ask clarification question {question_number} of "
        f"{cfg.clarification_questions}. Ask only this single question now. "
        "Do not answer the original request yet."
    )


def build_final_prompt(cfg: JarvisConfig, original_request: str, clarifications: list[tuple[str, str]]) -> str:
    """
    Build the final user message that includes the original request and all
    collected clarification Q&A pairs.
    """
    if not clarifications:
        return original_request

    parts = [f"Original request: {original_request}", "", "Clarification answers:"]
    for i, (question, answer) in enumerate(clarifications, start=1):
        parts.append(f"  Q{i}: {question}")
        parts.append(f"  A{i}: {answer}")
    parts.append("")
    parts.append("Now provide the final answer.")
    return "\n".join(parts)
