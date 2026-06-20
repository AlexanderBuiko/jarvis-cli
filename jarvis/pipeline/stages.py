"""
The per-stage agents and the stage registry.

Each agent owns one FSM stage and carries that stage's system-prompt fragment as
the single source of truth — both free-form chat (build_system_prompt) and the
orchestrator read the fragment from here, so they never drift apart.

Forward progress is automatic (an agent emits [[READY]] and the orchestrator
advances on the default edge). Backward/revision branches — validation FAIL and
execution REPLAN — are treated as user gates, so the pipeline never silently
loops; the user is asked to confirm a rework or a replan.
"""

import re

from .base import (
    GATE_APPROVAL,
    GATE_QUESTION,
    MARKER_NEEDS_USER,
    MARKER_READY,
    MARKER_STEP_DONE,
    EXPECTED_AWAIT_DONE_APPROVAL,
    EXPECTED_AWAIT_PLAN_APPROVAL,
    EXPECTED_AWAIT_USER,
    EXPECTED_DONE,
    EXPECTED_READY_TO_PLAN,
    EXPECTED_READY_TO_VALIDATE,
    EXPECTED_STEP_DONE,
    StageAgent,
    StageVerdict,
)


def parse_plan_steps(plan_text: str) -> list[str]:
    """Parse a free-text plan into an ordered list of step strings.

    Recognises numbered ("1." / "1)") and bulleted ("-", "*", "•") lines. If no
    such markers are present, falls back to treating each non-empty line as a
    step. Leading enumerator/bullet tokens are stripped from each step.
    """
    enumerator = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.*\S)\s*$")
    steps: list[str] = []
    for line in plan_text.splitlines():
        m = enumerator.match(line)
        if m:
            steps.append(m.group(1).strip())
    if steps:
        return steps
    # Fallback: no list markers — use non-empty lines as steps.
    return [ln.strip() for ln in plan_text.splitlines() if ln.strip()]


class ClarifierAgent(StageAgent):
    stage = "clarification"

    def system_fragment(self, task: dict) -> str:
        return (
            "The active task is in the CLARIFICATION stage — this is the ONLY stage where you may "
            "ask the user questions. Gather every requirement needed to produce the final result: "
            "goal, success criteria, scope, and any important constraints. If anything needed to "
            "produce a complete result is missing or ambiguous, ask about it now (you may ask "
            "several questions in one message). Do NOT ask about things the user already specified "
            "or that have an obvious sensible default. Only once you have everything you need, "
            "briefly restate your understanding — the later stages will NOT be able to ask the user."
        )

    def entry_message(self, task: dict) -> str:
        return (
            "Review what you know about this task. If you have enough to write a plan, restate your "
            "understanding. If anything essential is missing, ask only those questions."
        )

    def marker_protocol(self) -> str:
        return (
            "When you have enough information to produce a plan, end your reply with the line "
            f"{MARKER_READY}. If you still need information from the user, ask your questions and end "
            f"with {MARKER_NEEDS_USER}."
        )

    def interpret(self, markers: set[str]) -> StageVerdict:
        if MARKER_READY in markers:
            # Enough understood — advance to planning automatically (no confirmation).
            return StageVerdict(ready=True, expected_action=EXPECTED_READY_TO_PLAN)
        # Otherwise the agent needs answers: a free-text question gate.
        return StageVerdict(gate=GATE_QUESTION, expected_action=EXPECTED_AWAIT_USER)

    def record(self, task: dict, clean_text: str, verdict: StageVerdict) -> None:
        super().record(task, clean_text, verdict)
        if not task.get("description"):
            task["description"] = clean_text


class PlannerAgent(StageAgent):
    stage = "planning"

    def system_fragment(self, task: dict) -> str:
        return (
            "The active task is in the PLANNING stage. Produce a concrete, ordered, numbered plan "
            "of the STEPS REQUIRED TO PRODUCE THE DELIVERABLE. Each step must be an action that "
            "creates part of the final result (e.g. for a recipe: 'list the ingredients', 'write "
            "the cooking instructions') — NOT a question to the user. Requirements are already "
            "settled in clarification; do NOT ask the user anything, and choose sensible defaults "
            "for any minor unspecified detail. The user will approve the plan or ask for changes."
        )

    def entry_message(self, task: dict) -> str:
        return (
            "Produce the concrete, ordered, numbered plan of steps that will PRODUCE the deliverable. "
            "Do not include any steps that ask the user questions."
        )

    def marker_protocol(self) -> str:
        # No markers: producing a plan always leads to the plan-approval gate.
        return ""

    def input_ready(self, task: dict) -> tuple[bool, str]:
        if not task.get("description") and "clarification" not in (task.get("stage_outputs") or {}):
            return False, "planning needs a clarified task description first"
        return True, ""

    def interpret(self, markers: set[str]) -> StageVerdict:
        # A finished plan is a critical decision point: present Confirm / Reject.
        return StageVerdict(
            gate=GATE_APPROVAL,
            confirm_target="execution",
            reject_target="planning",   # reject reworks the plan in place
            expected_action=EXPECTED_AWAIT_PLAN_APPROVAL,
        )

    def record(self, task: dict, clean_text: str, verdict: StageVerdict) -> None:
        super().record(task, clean_text, verdict)
        task["plan"] = clean_text
        # Parse the plan into trackable steps and reset progress to the first one.
        task["plan_steps"] = parse_plan_steps(clean_text)
        task["step_index"] = 0
        task["current_step"] = task["plan_steps"][0] if task["plan_steps"] else ""


class ExecutorAgent(StageAgent):
    stage = "execution"

    def system_fragment(self, task: dict) -> str:
        return (
            "The active task is in the EXECUTION stage. Carry out the approved plan one step at a "
            "time. Each step must actually PRODUCE its part of the deliverable (write the content, "
            "do the work) and report that produced output — not merely describe or ask about it. "
            "Requirements were settled in clarification, so proceed with sensible defaults; only "
            "ask the user (and only then) if you are genuinely blocked and cannot make a reasonable "
            "assumption."
        )

    def entry_message(self, task: dict) -> str:
        steps = task.get("plan_steps") or []
        idx = task.get("step_index", 0)
        if steps and idx < len(steps):
            return (
                f"Work on step {idx + 1} of {len(steps)} now: {steps[idx]}\n"
                "Complete only this one step and report the result."
            )
        return "Begin executing the approved plan. Present the next step of work."

    def marker_protocol(self) -> str:
        return (
            "Work on the single current step only. End your reply with "
            f"{MARKER_STEP_DONE} if that step is done and further steps remain; with "
            f"{MARKER_READY} if that was the last step and all planned work is finished; or with "
            f"{MARKER_NEEDS_USER} if you need the user's input to continue."
        )

    def input_ready(self, task: dict) -> tuple[bool, str]:
        if not task.get("plan"):
            return False, "execution needs an approved plan first"
        return True, ""

    def interpret(self, markers: set[str]) -> StageVerdict:
        if MARKER_READY in markers:
            # All steps done — advance to validation automatically.
            return StageVerdict(ready=True, expected_action=EXPECTED_READY_TO_VALIDATE)
        if MARKER_STEP_DONE in markers:
            # Progress: this step is complete, but more remain — re-run execution.
            return StageVerdict(continue_stage=True, expected_action=EXPECTED_STEP_DONE)
        # The agent needs the user's input to continue this step: free-text gate.
        return StageVerdict(gate=GATE_QUESTION, expected_action=EXPECTED_AWAIT_USER)

    def record(self, task: dict, clean_text: str, verdict: StageVerdict) -> None:
        steps = task.get("plan_steps") or []
        idx = task.get("step_index", 0)
        # Accumulate a per-step execution log so every step persists (and survives a
        # thread switch), rather than overwriting with only the latest step.
        outputs = task.setdefault("stage_outputs", {})
        label = f"[step {idx + 1}/{len(steps)}]" if steps else "[step]"
        prev = outputs.get("execution", "")
        outputs["execution"] = (prev + "\n\n" if prev else "") + f"{label} {clean_text}"
        # Advance the in-progress pointer.
        if verdict.expected_action == EXPECTED_STEP_DONE:
            task["step_index"] = min(idx + 1, len(steps))
        elif verdict.ready:
            task["step_index"] = len(steps)  # every step complete
        new_idx = task.get("step_index", 0)
        task["current_step"] = steps[new_idx] if new_idx < len(steps) else ""


class ValidatorAgent(StageAgent):
    stage = "validation"

    def system_fragment(self, task: dict) -> str:
        return (
            "The active task is in the VALIDATION stage. Verify the result against the plan and the "
            "success criteria, and report clearly whether each criterion is met. The user will then "
            "decide whether to finish the task or send it back for rework."
        )

    def entry_message(self, task: dict) -> str:
        return "Validate the result against the plan and the success criteria, and summarise findings."

    def marker_protocol(self) -> str:
        # No markers: the human always decides at validation (Confirm = done, Reject = rework).
        return ""

    def input_ready(self, task: dict) -> tuple[bool, str]:
        if not task.get("plan"):
            return False, "validation needs a plan to check against"
        return True, ""

    def interpret(self, markers: set[str]) -> StageVerdict:
        # Finishing the task is a critical decision point: present Confirm / Reject.
        return StageVerdict(
            gate=GATE_APPROVAL,
            confirm_target="done",
            reject_target="execution",  # reject sends it back for rework
            expected_action=EXPECTED_AWAIT_DONE_APPROVAL,
        )


class DoneAgent(StageAgent):
    """Terminal stage — assemble the final deliverable from the work done."""
    stage = "done"

    def system_fragment(self, task: dict) -> str:
        return (
            "The task is being finalised. Output exactly:\n"
            "  1. A single line beginning with 'SUMMARY: ' giving a one-sentence description of "
            "the deliverable.\n"
            "  2. A blank line.\n"
            "  3. The COMPLETE final deliverable assembled from the work produced during "
            "execution — the actual result the task set out to create, ready to hand off.\n"
            "No other meta-commentary (e.g. 'the task is finished')."
        )

    def entry_message(self, task: dict) -> str:
        return "Finalise the task: a 'SUMMARY: ' line, a blank line, then the complete deliverable."

    def marker_protocol(self) -> str:
        return ""

    def interpret(self, markers: set[str]) -> StageVerdict:
        return StageVerdict(expected_action=EXPECTED_DONE)


# The stage registry: the single place mapping FSM stages to their agents.
STAGE_AGENTS: dict[str, StageAgent] = {
    agent.stage: agent
    for agent in (ClarifierAgent(), PlannerAgent(), ExecutorAgent(), ValidatorAgent(), DoneAgent())
}


def stage_system_fragment(stage: str, task: dict) -> str | None:
    """Return the system-prompt fragment for a stage, or None if unknown.

    Used by build_system_prompt so the stage role has a single source of truth.
    """
    agent = STAGE_AGENTS.get(stage)
    return agent.system_fragment(task) if agent else None
