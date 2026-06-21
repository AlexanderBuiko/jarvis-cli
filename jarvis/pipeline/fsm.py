"""
Task FSM policy — the single source of truth for valid task states and the
transitions permitted between them.

Separated from persistence (``TaskStore``) so the rules can be reasoned about and
tested independently of where task state is stored. The KB's requirement is that
stage transitions are enforced in code (never by the model), surviving
summarisation and compaction; this module is that enforcement point.

The first entry of each transition list is the default forward edge; later
entries are revision/branch targets that must be requested explicitly.
"""

# Task state machine. Basic stages; expand with caution (the KB warns against
# removing core stages but allows adding them).
STAGES: tuple[str, ...] = ("clarification", "planning", "execution", "validation", "done")

ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "clarification": ["planning"],
    "planning":      ["execution"],
    "execution":     ["validation", "planning"],  # validate, or back to planning to revise
    "validation":    ["done", "execution", "planning"],  # done, rework execution, or re-plan
    "done":          [],
}


def default_target(stage: str) -> str | None:
    """The default forward edge from ``stage``, or None if terminal/unknown."""
    allowed = ALLOWED_TRANSITIONS.get(stage, [])
    return allowed[0] if allowed else None


def is_allowed(current: str, target: str) -> bool:
    """True when ``current → target`` is a permitted transition."""
    return target in ALLOWED_TRANSITIONS.get(current, [])


def resolve_transition(current: str, target: str | None) -> str:
    """Validate and resolve a transition, returning the resulting stage.

    ``target`` defaults to the forward edge when omitted. Raises ValueError if
    the stage is terminal or the requested transition is not permitted — this is
    the code-level guard that makes "the assistant cannot skip a stage" real.
    """
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if not allowed:
        raise ValueError(f"task is already in the terminal stage '{current}'")
    if target is None:
        target = allowed[0]
    if target not in allowed:
        raise ValueError(
            f"cannot move {current} → {target} (allowed: {', '.join(allowed)})"
        )
    return target
