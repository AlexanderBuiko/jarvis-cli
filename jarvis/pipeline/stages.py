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
    MARKER_FAIL,
    MARKER_NEEDS_USER,
    MARKER_PASS,
    MARKER_READY,
    MARKER_REPLAN,
    MARKER_STEP_DONE,
    EXPECTED_AWAIT_USER,
    EXPECTED_DONE,
    EXPECTED_IN_PROGRESS,
    EXPECTED_NEEDS_REPLAN,
    EXPECTED_NEEDS_REWORK,
    EXPECTED_READY_TO_EXECUTE,
    EXPECTED_READY_TO_FINISH,
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
            "The active task is in the CLARIFICATION stage. Make sure the goal, success criteria, "
            "scope, and constraints are clear. Ask clarifying questions ONLY about details that are "
            "genuinely missing or ambiguous — do not ask about things the user already specified or "
            "that have a sensible default. When you believe you understand the task, briefly restate "
            "your understanding and tell the user to run `task next` when they are ready to plan."
        )

    def entry_message(self, task: dict) -> str:
        return (
            "Review what you know about this task. If you have enough to write a plan, restate your "
            "understanding. If anything essential is missing, ask only those questions."
        )

    def marker_protocol(self) -> str:
        return (
            "When you have enough information to produce a plan, end your reply with the line "
            f"{MARKER_READY}. If you still need information from the user, end with {MARKER_NEEDS_USER}."
        )

    def interpret(self, markers: set[str]) -> StageVerdict:
        if MARKER_READY in markers:
            return StageVerdict(ready=True, expected_action=EXPECTED_READY_TO_PLAN)
        # Clarification is a user gate by nature: absent an explicit READY, wait.
        return StageVerdict(needs_user=True, expected_action=EXPECTED_AWAIT_USER)

    def record(self, task: dict, clean_text: str, verdict: StageVerdict) -> None:
        super().record(task, clean_text, verdict)
        if not task.get("description"):
            task["description"] = clean_text


class PlannerAgent(StageAgent):
    stage = "planning"

    def system_fragment(self, task: dict) -> str:
        return (
            "The active task is in the PLANNING stage. Produce a concrete, ordered plan that would "
            "complete the task. Present the plan and invite the user to adjust it; tell them to run "
            "`task next` when they approve it and want to start execution."
        )

    def entry_message(self, task: dict) -> str:
        return "Produce the concrete, ordered plan for this task now."

    def marker_protocol(self) -> str:
        return f"When the plan is complete, end your reply with the line {MARKER_READY}."

    def input_ready(self, task: dict) -> tuple[bool, str]:
        if not task.get("description") and "clarification" not in (task.get("stage_outputs") or {}):
            return False, "planning needs a clarified task description first"
        return True, ""

    def interpret(self, markers: set[str]) -> StageVerdict:
        if MARKER_READY in markers:
            return StageVerdict(ready=True, expected_action=EXPECTED_READY_TO_EXECUTE)
        return StageVerdict(expected_action=EXPECTED_IN_PROGRESS)

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
            "The active task is in the EXECUTION stage. Carry out the plan: present the work (e.g. the "
            "problems to solve) and respond to the user's results as they come. When the planned work "
            "is finished, tell the user to run `task next` to move to validation."
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
            f"{MARKER_READY} if that was the last step and all planned work is finished; with "
            f"{MARKER_NEEDS_USER} if you need the user's input to continue; or with {MARKER_REPLAN} "
            "if the plan itself must change."
        )

    def input_ready(self, task: dict) -> tuple[bool, str]:
        if not task.get("plan"):
            return False, "execution needs an approved plan first"
        return True, ""

    def interpret(self, markers: set[str]) -> StageVerdict:
        if MARKER_REPLAN in markers:
            # Backward branch -> gate: ask the user to confirm a replan.
            return StageVerdict(
                needs_user=True, next_target="planning", expected_action=EXPECTED_NEEDS_REPLAN
            )
        if MARKER_READY in markers:
            return StageVerdict(ready=True, expected_action=EXPECTED_READY_TO_VALIDATE)
        if MARKER_STEP_DONE in markers:
            # Progress: this step is complete, but more remain — re-run execution.
            return StageVerdict(continue_stage=True, expected_action=EXPECTED_STEP_DONE)
        return StageVerdict(needs_user=True, expected_action=EXPECTED_AWAIT_USER)

    def record(self, task: dict, clean_text: str, verdict: StageVerdict) -> None:
        super().record(task, clean_text, verdict)
        steps = task.get("plan_steps") or []
        if verdict.expected_action == EXPECTED_STEP_DONE:
            # Advance the in-progress pointer to the next step.
            task["step_index"] = min(task.get("step_index", 0) + 1, len(steps))
        elif verdict.ready:
            # All work finished — every step is complete.
            task["step_index"] = len(steps)
        idx = task.get("step_index", 0)
        task["current_step"] = steps[idx] if idx < len(steps) else ""


class ValidatorAgent(StageAgent):
    stage = "validation"

    def system_fragment(self, task: dict) -> str:
        return (
            "The active task is in the VALIDATION stage. Verify the result against the plan and the "
            "success criteria. If the criteria are met, tell the user to run `task next` to finish the "
            "task. If they are not met, explain what is wrong and tell the user to run `task back` to "
            "return to execution."
        )

    def entry_message(self, task: dict) -> str:
        return "Validate the result against the plan and the success criteria."

    def marker_protocol(self) -> str:
        return (
            f"End your reply with {MARKER_PASS} if the success criteria are fully met, or {MARKER_FAIL} "
            "if they are not."
        )

    def input_ready(self, task: dict) -> tuple[bool, str]:
        if not task.get("plan"):
            return False, "validation needs a plan to check against"
        return True, ""

    def interpret(self, markers: set[str]) -> StageVerdict:
        if MARKER_PASS in markers:
            return StageVerdict(ready=True, next_target="done", expected_action=EXPECTED_READY_TO_FINISH)
        if MARKER_FAIL in markers:
            # Backward branch -> gate: surface the failure, let the user drive rework.
            return StageVerdict(
                needs_user=True, next_target="execution", expected_action=EXPECTED_NEEDS_REWORK
            )
        return StageVerdict(needs_user=True, expected_action=EXPECTED_AWAIT_USER)


class DoneAgent(StageAgent):
    """Terminal stage — no work, no markers; present only for a uniform registry."""
    stage = "done"

    def system_fragment(self, task: dict) -> str:
        return "The active task is DONE. Provide a brief closing summary if useful."

    def entry_message(self, task: dict) -> str:
        return "The task is finished. Please give a brief closing summary."

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
