"""
Orchestrator — drives the task finite state machine across the stage agents.

It is the only component that advances stages during an autonomous run, and it
always advances through TaskStore.advance_stage (so ALLOWED_TRANSITIONS is
enforced in code — the LLM never self-transitions). Forward edges roll on
automatically when a stage reports [[READY]]; backward branches are surfaced as
gates so the pipeline cannot silently loop.
"""

from dataclasses import dataclass
from typing import Callable

from .base import StageAgent, StageVerdict


@dataclass
class StageResult:
    """One stage execution within an orchestrator run."""
    stage: str
    text: str = ""
    verdict: StageVerdict | None = None
    blocked: str | None = None   # set when the stage's input contract was not satisfied
    advanced_to: str | None = None  # the stage advanced to afterwards, if any


# A run-turn callable: (entry_message, extra_system) -> raw assistant text.
RunTurn = Callable[[str, str], str]


class Orchestrator:
    # Safety cap so a misbehaving model can never loop the FSM forever. Generous
    # enough for step-wise execution of a multi-step plan plus the other stages.
    MAX_STEPS = 40

    def __init__(self, agents: dict[str, StageAgent], tasks) -> None:
        self._agents = agents
        self._tasks = tasks

    def run(self, task: dict, run_turn: RunTurn, autonomy: str) -> list[StageResult]:
        """Drive the FSM from the task's current stage.

        Runs the current stage's agent; on [[READY]] (and autonomy == 'auto')
        advances on the chosen edge and continues, until a gate (needs_user /
        not ready / blocked input), the terminal stage, or MAX_STEPS.
        """
        results: list[StageResult] = []
        for _ in range(self.MAX_STEPS):
            stage = task["stage"]
            agent = self._agents.get(stage)
            if agent is None or stage == "done":
                break

            ok, reason = agent.input_ready(task)
            if not ok:
                results.append(StageResult(stage=stage, blocked=reason))
                break

            raw = run_turn(agent.entry_message(task), agent.marker_protocol())
            verdict = agent.process(task, raw)
            self._tasks.save(task)
            result = StageResult(stage=stage, text=verdict.clean_text, verdict=verdict)
            results.append(result)

            if verdict.needs_user:
                break
            # Made progress within the stage (e.g. one plan step done) — re-run the
            # same stage rather than advancing, so step-wise work continues.
            if verdict.continue_stage:
                if autonomy != "auto":
                    break
                continue
            if not verdict.ready:
                break
            if autonomy != "auto":
                break

            new_stage = self._tasks.advance_stage(task, verdict.next_target)
            self._tasks.save(task)
            result.advanced_to = new_stage
        return results
