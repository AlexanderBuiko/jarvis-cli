"""
ParallelExecutionRunner — runs the execution stage's steps concurrently.

It plugs into the same ``StageRunner`` seam as the validation swarm. For the
``execution`` stage (and only when ``execution_agents`` > 1) it executes the plan's
steps with a pool of executor agents, honouring the dependency graph the planner
annotated (``plan_deps``): independent steps run at once, dependent steps wait for
their inputs. Steps are run in topological *waves* — every step in a wave has all
its dependencies satisfied, so the waves run in order while the steps inside one
wave run in parallel. For any other stage — or when parallel execution is off — it
delegates to the wrapped runner unchanged.

Like the swarm: every model call goes through ``LLMGateway`` and is accounted onto
the task. The runner writes the assembled execution output itself and flags the
turn (``_exec_recorded``) so ``ExecutorAgent.record`` doesn't re-append it; it emits
``[[READY]]`` so the orchestrator advances to validation on the normal forward edge
(the FSM is untouched).
"""

from concurrent.futures import ThreadPoolExecutor

from ..llm.gateway import LLMGateway
from .base import MARKER_READY
from .runner import LLMStageRunner, StageRunner
from .stages import ExecutorAgent, assemble_deliverable


def execution_waves(deps: list[list[int]]) -> list[list[int]]:
    """Topological waves: each wave is the steps whose deps are all already done.

    deps are pre-sanitised to earlier steps (no cycles), but a guard still breaks
    any stuck state by forcing the lowest remaining step through on its own.
    """
    n = len(deps)
    done: set[int] = set()
    remaining = set(range(n))
    waves: list[list[int]] = []
    while remaining:
        wave = [i for i in sorted(remaining) if all(d in done for d in deps[i])]
        if not wave:
            wave = [min(remaining)]
        waves.append(wave)
        done.update(wave)
        remaining.difference_update(wave)
    return waves


class ParallelExecutionRunner:
    """A ``StageRunner`` that parallelises the execution stage and delegates the rest."""

    def __init__(
        self,
        gateway: LLMGateway,
        config,
        base_runner: StageRunner,
        tasks,
        executor: ExecutorAgent | None = None,
    ) -> None:
        self._gateway = gateway
        self._config = config
        self._base = base_runner
        self._tasks = tasks
        self._executor = executor or ExecutorAgent()

    def run(self, task: dict, entry_message: str, extra_system: str = "") -> str:
        n = int(self._config.runtime.get("execution_agents", 1) or 1)
        steps = task.get("plan_steps") or []
        if task.get("stage") != "execution" or n <= 1 or len(steps) <= 1:
            return self._base.run(task, entry_message, extra_system)

        # Missing/mismatched annotations ⇒ treat every step as independent (the
        # opt-in is an explicit choice to parallelise; new plans carry real deps).
        deps = task.get("plan_deps") or []
        if len(deps) != len(steps):
            deps = [[] for _ in steps]

        params = self._params()
        system = (
            f"{self._executor.system_fragment(task)}\n\n"
            f"## Goal\n{task.get('description') or '(none stated)'}\n\n"
            f"## Full plan\n{task.get('plan') or '(none stated)'}"
        )
        results: dict[int, str] = {}
        step_calls: dict[int, list[dict]] = {}

        # Live per-step status the REPL's step table polls so several concurrently
        # running steps are all shown in-progress (not just the first). Pre-sized, so
        # only element assignment happens under concurrency (GIL-atomic — safe to read
        # from the render thread). Cleared in ExecutorAgent.record before persisting.
        status = task["_step_status"] = ["pending"] * len(steps)

        for wave in execution_waves(deps):
            workers = min(n, len(wave))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                done = pool.map(
                    lambda i: (i, *self._run_step(i, steps, deps, results, system, params, status)),
                    wave,
                )
            for i, text, calls in done:
                results[i] = text
                step_calls[i] = calls

        # Assemble the step outputs (in plan order) into the execution log, then bill
        # every call to the task in step order so accounting is deterministic.
        assembled = "\n\n".join(
            f"[step {i + 1}/{len(steps)}] {results.get(i, '').strip()}" for i in range(len(steps))
        )
        api_calls: list[dict] = []
        for i in range(len(steps)):
            for record in step_calls.get(i, []):
                record["index"] = len(api_calls) + 1
                api_calls.append(record)
        LLMStageRunner._account(task, api_calls)

        task.setdefault("stage_outputs", {})["execution"] = assembled
        task["step_index"] = len(steps)
        task["current_step"] = ""
        task["_exec_recorded"] = True  # ExecutorAgent.record must not re-append

        clean = assemble_deliverable(assembled)
        history = task.setdefault("messages", [])
        history.append({"role": "user", "content": entry_message})
        history.append({"role": "assistant", "content": clean})
        # READY ⇒ the orchestrator advances execution → validation on the forward edge.
        return f"{clean}\n{MARKER_READY}"

    def _run_step(self, i, steps, deps, results, system, params, status) -> tuple[str, list[dict]]:
        status[i] = "running"
        dep_context = "\n\n".join(
            f"[step {d + 1}] {results[d]}" for d in deps[i] if d in results
        )
        msg = (
            f"Work on step {i + 1} of {len(steps)} now: {steps[i]}\n"
            "Complete only this one step and report the produced result."
        )
        if dep_context:
            msg += f"\n\nOutputs of the steps this one builds on:\n{dep_context}"
        calls: list[dict] = []
        completion = self._gateway.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": msg}],
            params, label=f"parallel_exec:step_{i + 1}", api_calls=calls,
        )
        status[i] = "done"
        return completion.text.strip(), calls

    def _params(self) -> dict:
        runtime = self._config.runtime
        return {"model": runtime["model"]} if "model" in runtime else {}
