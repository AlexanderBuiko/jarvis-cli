"""
Orchestrator — runs the task finite state machine one turn at a time.

It executes the current stage's agent once and, when that stage's work is
complete with no decision needed, advances on the forward edge (always through
TaskStore.advance_stage, so ALLOWED_TRANSITIONS stays the single code-enforced
source of truth — the LLM never self-transitions). When a stage hits a gate
(a free-text question, or a critical Confirm/Reject approval) it stops and
returns; the interactive driver (jarvis/repl/loop.py) handles the gate and calls
step() again. This keeps the FSM logic here and the I/O in the driver.
"""

from dataclasses import dataclass

from .base import StageAgent, StageVerdict
from .runner import StageRunner


@dataclass
class StageResult:
    """The outcome of running one stage turn."""
    stage: str
    text: str = ""
    verdict: StageVerdict | None = None
    blocked: str | None = None      # set when the stage's input contract was not satisfied
    advanced_to: str | None = None  # the stage advanced to afterwards, if any


class Orchestrator:
    def __init__(self, agents: dict[str, StageAgent], tasks, runner: StageRunner) -> None:
        self._agents = agents
        self._tasks = tasks
        self._runner = runner

    def step(self, task: dict, extra_instruction: str = "") -> StageResult:
        """Run the current stage's agent once and return the result.

        extra_instruction (e.g. a user's answer or rework feedback) is appended to
        the stage's entry message for this turn only. Auto-advances on the forward
        edge when the stage reports ready with no gate; otherwise returns at the
        gate / progress point for the driver to handle.
        """
        stage = task["stage"]
        agent = self._agents.get(stage)
        if agent is None:
            return StageResult(stage=stage, blocked=f"no agent for stage '{stage}'")

        ok, reason = agent.input_ready(task)
        if not ok:
            return StageResult(stage=stage, blocked=reason)

        entry = agent.entry_message(task)
        if extra_instruction:
            entry = f"{entry}\n\n{extra_instruction}"
        raw = self._runner.run(task, entry, agent.marker_protocol())
        verdict = agent.process(task, raw)
        self._tasks.save(task)
        result = StageResult(stage=stage, text=verdict.clean_text, verdict=verdict)

        # A gate or in-stage progress: stop here, the driver decides what is next.
        if verdict.gate or verdict.continue_stage:
            return result
        # Stage complete with no decision needed: advance on the forward edge.
        if verdict.ready:
            result.advanced_to = self._tasks.advance_stage(task, verdict.next_target)
            self._tasks.save(task)
        return result
