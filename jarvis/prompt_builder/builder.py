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


# Stage transitions are controlled explicitly by the user via `task next` /
# `task back`; the agent only does the work of the current stage and never moves
# stages itself (deterministic, code-enforced control). Each stage describes its
# job and tells the user how to proceed when they are ready.
_TASK_STAGE_INSTRUCTIONS: dict[str, str] = {
    "clarification": (
        "The active task is in the CLARIFICATION stage. Make sure the goal, success criteria, "
        "scope, and constraints are clear. Ask clarifying questions ONLY about details that are "
        "genuinely missing or ambiguous — do not ask about things the user already specified or "
        "that have a sensible default. When you believe you understand the task, briefly restate "
        "your understanding and tell the user to run `task next` when they are ready to plan."
    ),
    "planning": (
        "The active task is in the PLANNING stage. Produce a concrete, ordered plan that would "
        "complete the task. Present the plan and invite the user to adjust it; tell them to run "
        "`task next` when they approve it and want to start execution."
    ),
    "execution": (
        "The active task is in the EXECUTION stage. Carry out the plan: present the work (e.g. the "
        "problems to solve) and respond to the user's results as they come. When the planned work "
        "is finished, tell the user to run `task next` to move to validation."
    ),
    "validation": (
        "The active task is in the VALIDATION stage. Verify the result against the plan and the "
        "success criteria. If the criteria are met, tell the user to run `task next` to finish the "
        "task. If they are not met, explain what is wrong and tell the user to run `task back` to "
        "return to execution."
    ),
    "done": (
        "The active task is DONE. Provide a brief closing summary if useful."
    ),
}

_TASK_CONTROL_NOTE = (
    "Stage control: you must NOT change the task stage yourself and must not claim a stage is "
    "switched. Stage transitions happen only when the user runs `task next` (forward) or "
    "`task back` (validation → execution). Just do the current stage's work and, when ready, tell "
    "the user which command to run."
)


def build_system_prompt(
    params: dict[str, Any],
    task: dict[str, Any] | None = None,
    loaded_memory: dict[str, str] | None = None,
    profile: str | None = None,
    invariants: str | None = None,
) -> str:
    """Return the system prompt for the current configuration.

    Assembly order (the mentor's "explicitly decide what to add"):
      base → solution-strategy → always-on profile → always-on invariants →
      current task stage role → on-demand loaded memory.

    profile and invariants come from the always-on long-term-memory files and
    are included on every request; loaded_memory holds on-demand files.
    """
    parts = [_BASE_SYSTEM_PROMPT]

    strategy = params.get("solution_strategy", "direct")
    if strategy == "step_by_step":
        parts.append(_STEP_BY_STEP_INSTRUCTION)
    elif strategy == "expert_panel":
        parts.append(_EXPERT_PANEL_INSTRUCTION)

    if profile and profile.strip():
        parts.append(f"[User Profile — style, constraints, context]\n{profile.strip()}")

    if invariants and invariants.strip():
        parts.append(
            "[Invariants — hard rules you MUST NOT violate under any circumstances, even if the "
            f"user asks]\n{invariants.strip()}"
        )

    if task is not None:
        stage = task.get("stage", "clarification")
        stage_instruction = _TASK_STAGE_INSTRUCTIONS.get(stage)
        if stage_instruction:
            parts.append(stage_instruction)
        if stage != "done":
            parts.append(_TASK_CONTROL_NOTE)

    if loaded_memory:
        for name, content in loaded_memory.items():
            parts.append(f"[Long-Term Memory — {name}]\n{content.strip()}")

    return "\n\n".join(parts)


_STAGE_ORDER: tuple[str, ...] = ("clarification", "planning", "execution", "validation", "done")


def build_working_memory_block(task: dict[str, Any]) -> list[dict]:
    """Return a pseudo-exchange describing the current task state.

    Injected ahead of the conversation history so the model always sees the
    task's stage, plan, and progress without the user repeating it. Lives
    outside the message history, so it survives compression and thread switches.

    Stage-scoped on purpose: the tutor's anti-pattern is "include everything saved
    in every prompt." So instead of dumping every stage's full output every turn,
    we carry the durable essentials (plan, current step, progress) plus only the
    *immediately preceding* stage's result — enough to resume without re-explaining,
    without unbounded context growth as the task progresses.
    """
    lines = [
        f"[Working Memory — Task: {task.get('name', '')}]",
        f"Stage: {task.get('stage', '')}",
    ]
    if task.get("current_step"):
        lines.append(f"Current step: {task['current_step']}")
    if task.get("expected_action"):
        lines.append(f"Expected action: {task['expected_action']}")
    if task.get("description"):
        lines.append(f"Description: {task['description']}")
    if task.get("plan"):
        lines.append("Plan:")
        lines.append(task["plan"])
    if task.get("completed"):
        lines.append("Completed:")
        lines += [f"  - {item}" for item in task["completed"]]
    if task.get("remaining"):
        lines.append("Remaining:")
        lines += [f"  - {item}" for item in task["remaining"]]
    if task.get("notes"):
        lines.append(f"Notes: {task['notes']}")

    # Only the immediately preceding stage's result — the durable hand-off that
    # lets work resume in a different thread (where the chat history is gone)
    # without re-dumping the whole task history every turn.
    prev_output = _preceding_stage_output(task)
    if prev_output:
        prev_stage, text = prev_output
        lines.append(f"Result from the previous stage [{prev_stage}]:")
        lines += [f"  {ln}" for ln in text.splitlines()]

    return [
        {"role": "user", "content": "\n".join(lines)},
        {"role": "assistant", "content": "Understood, I have the current task context."},
    ]


def _preceding_stage_output(task: dict[str, Any]) -> tuple[str, str] | None:
    """Return (stage, output) for the most recent completed stage before the current one."""
    outputs = task.get("stage_outputs") or {}
    if not outputs:
        return None
    stage = task.get("stage", "clarification")
    try:
        idx = _STAGE_ORDER.index(stage)
    except ValueError:
        idx = len(_STAGE_ORDER)
    # Walk backwards from the stage just before the current one.
    for prev in reversed(_STAGE_ORDER[:idx]):
        if outputs.get(prev):
            return prev, outputs[prev]
    return None


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


def build_invariant_check_prompt(invariants: str, response_text: str) -> str:
    """Build the prompt that checks a reply against the invariant list.

    Acts as a "linter for requirements expressed in natural language": the model
    must answer with exactly OK when the reply violates nothing, or list the
    concrete violations otherwise.
    """
    return (
        "You are a strict compliance checker. Below is a list of INVARIANTS (hard rules) and an "
        "ASSISTANT REPLY. Determine whether the reply violates any invariant.\n\n"
        f"INVARIANTS:\n{invariants.strip()}\n\n"
        f"ASSISTANT REPLY:\n{response_text.strip()}\n\n"
        "If the reply violates no invariant, respond with exactly: OK\n"
        "Otherwise, list each violation on its own line as '- <which invariant> : <how it is "
        "violated>'. Output only OK or the violation list, with no other commentary."
    )


def build_invariant_rework_prompt(invariants: str, response_text: str, violations: str) -> str:
    """Build the prompt asking the agent to rewrite a reply to satisfy invariants."""
    return (
        "Your previous reply violated one or more invariants (hard rules). Rewrite it so it fully "
        "satisfies every invariant while still addressing the user's request. Do not mention the "
        "invariants, the violations, or this correction — output only the corrected reply.\n\n"
        f"INVARIANTS:\n{invariants.strip()}\n\n"
        f"VIOLATIONS FOUND:\n{violations.strip()}\n\n"
        f"YOUR PREVIOUS REPLY:\n{response_text.strip()}"
    )


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


_PROFILE_NO_CHANGE = "NO CHANGE"


def build_profile_style_prompt(current_style: str, recent_activity: list[dict]) -> str:
    """Build the prompt that proposes an updated profile Style section.

    The model sees the current Style section plus a compact log of recent
    interactions and returns a revised Style section (bullet lines only, no
    heading). It must restrict itself to *style/format* preferences inferable
    from behaviour (answer length, tone, code examples, step-by-step, etc.) and
    must NOT invent constraints, identity, or domain rules. When recent behaviour
    does not justify any change, it returns the sentinel NO CHANGE.
    """
    lines = ["Recent interactions (oldest first):"]
    for i, rec in enumerate(recent_activity, 1):
        preview = rec.get("user_input", "").replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        lines.append(
            f"  {i}. user_chars={rec.get('user_chars')} "
            f"response_chars={rec.get('response_chars')} "
            f"solution_strategy={rec.get('solution_strategy')} "
            f"context_strategy={rec.get('context_strategy')} "
            f"in_task={rec.get('had_task')}"
        )
        lines.append(f"      msg: {preview}")
    activity = "\n".join(lines)

    return (
        "You personalise an AI assistant by maintaining the STYLE section of a user "
        "profile. You are given the current Style section and a log of the user's recent "
        "interactions. Infer durable STYLE and FORMAT preferences only — for example: "
        "preferred answer length (concise vs detailed), tone (formal vs conversational), "
        "whether they want code examples, step-by-step reasoning, bullet lists, language, etc.\n\n"
        "Strict rules:\n"
        "  • Only adjust style/format preferences. Do NOT add constraints, prohibitions, "
        "tech-stack rules, the user's identity, goals, or any behavioural rule — those live "
        "elsewhere and are off-limits.\n"
        "  • Only change something when the recent behaviour clearly and repeatedly supports "
        "it. Preserve existing lines that are still valid.\n"
        "  • Keep it short: a handful of '- ' bullet lines.\n"
        f"  • If recent behaviour does not justify any change, output exactly: {_PROFILE_NO_CHANGE}\n\n"
        f"CURRENT STYLE SECTION:\n{current_style.strip() or '(empty)'}\n\n"
        f"{activity}\n\n"
        "Output only the revised Style section as bullet lines (no '## Style' heading, no "
        f"commentary), or exactly {_PROFILE_NO_CHANGE}."
    )


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
