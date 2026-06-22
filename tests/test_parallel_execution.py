"""
Tests for parallel execution (jarvis/pipeline/parallel.py) and the plan dependency
graph (jarvis/pipeline/stages.parse_plan), plus the rework-log reset.

All model access is through a FakeEngine behind the LLMGateway — no network.
"""

import re
import tempfile
import unittest
from pathlib import Path

from jarvis.config.manager import ConfigManager
from jarvis.llm.gateway import LLMGateway
from jarvis.pipeline.base import MARKER_READY
from jarvis.pipeline.orchestrator import Orchestrator
from jarvis.pipeline.parallel import ParallelExecutionRunner, execution_waves
from jarvis.pipeline.stages import STAGE_AGENTS, assemble_deliverable, parse_plan
from jarvis.session.task_store import TaskStore
from tests.fake_engine import FakeEngine


class ParsePlanTest(unittest.TestCase):
    def test_dependencies_parsed_and_stripped(self):
        steps, deps = parse_plan("1. boil water [after: none]\n2. add pasta [after: 1]\n3. drain [after: 1, 2]")
        self.assertEqual(steps, ["boil water", "add pasta", "drain"])
        self.assertEqual(deps, [[], [0], [0, 1]])

    def test_unannotated_plan_is_all_independent(self):
        steps, deps = parse_plan("1. a\n2. b\n3. c")
        self.assertEqual(steps, ["a", "b", "c"])
        self.assertEqual(deps, [[], [], []])

    def test_forward_and_self_references_dropped(self):
        # Step 1 -> after 2 (forward) and step 2 -> after 2 (self) are both dropped.
        _, deps = parse_plan("1. a [after: 2]\n2. b [after: 2]")
        self.assertEqual(deps, [[], []])


class ExecutionWavesTest(unittest.TestCase):
    def test_topological_waves(self):
        self.assertEqual(execution_waves([[], [0], [0], [1, 2]]), [[0], [1, 2], [3]])

    def test_all_independent_is_one_wave(self):
        self.assertEqual(execution_waves([[], [], []]), [[0, 1, 2]])

    def test_chain_is_sequential_waves(self):
        self.assertEqual(execution_waves([[], [0], [1]]), [[0], [1], [2]])


def _exec_task(store: TaskStore, deps=None) -> dict:
    task = store.new_task("demo")
    task["stage"] = "execution"
    task["description"] = "cook pasta tutorial"
    task["plan"] = "the plan"
    task["plan_steps"] = ["list ingredients", "write boiling steps", "write draining steps"]
    task["plan_deps"] = deps if deps is not None else [[], [], []]
    task["step_index"] = 0
    store.save(task)
    return task


class _RecordingRunner:
    def __init__(self):
        self.calls = []

    def run(self, task, entry_message, extra_system=""):
        self.calls.append(task["stage"])
        return "base-output"


def _step_responder(messages, params):
    """Echo a deterministic output naming the step number from the user message."""
    user = messages[-1]["content"]
    m = re.search(r"step (\d+) of", user)
    return f"OUTPUT for step {m.group(1)}" if m else "OUTPUT"


class ParallelRunnerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tasks = TaskStore(Path(self._tmp.name))
        self.config = ConfigManager()

    def tearDown(self):
        self._tmp.cleanup()

    def _runner(self, engine, base=None):
        return ParallelExecutionRunner(
            LLMGateway(engine), self.config, base or _RecordingRunner(), self.tasks
        )

    def test_delegates_non_execution_stage(self):
        self.config.set("execution_agents", "4")
        base = _RecordingRunner()
        runner = self._runner(FakeEngine(), base)
        task = self.tasks.new_task("demo")  # clarification
        self.assertEqual(runner.run(task, "entry"), "base-output")
        self.assertEqual(base.calls, ["clarification"])

    def test_off_by_default_delegates_execution(self):
        base = _RecordingRunner()  # execution_agents defaults to 1
        runner = self._runner(FakeEngine(), base)
        task = _exec_task(self.tasks)
        self.assertEqual(runner.run(task, "go"), "base-output")
        self.assertEqual(base.calls, ["execution"])

    def test_runs_every_step_and_emits_ready(self):
        self.config.update(["model=test/m", "execution_agents=3"])
        engine = FakeEngine(responder=_step_responder)
        runner = self._runner(engine)
        task = _exec_task(self.tasks)
        out = runner.run(task, "go")
        self.assertEqual(len(engine.calls), 3)         # one model call per step
        self.assertIn(MARKER_READY, out)
        self.assertEqual(task["step_index"], 3)        # all steps complete
        # The execution log holds every step's output, labelled.
        log = task["stage_outputs"]["execution"]
        for k in (1, 2, 3):
            self.assertIn(f"OUTPUT for step {k}", log)

    def test_accounting_accumulates_all_step_calls(self):
        self.config.update(["model=test/m", "execution_agents=3"])
        runner = self._runner(FakeEngine(responder=_step_responder))
        task = _exec_task(self.tasks)
        runner.run(task, "go")
        self.assertEqual(task["api_call_count"], 3)
        self.assertEqual(task["total_tokens"], 6)      # FakeEngine: 2 tokens/call

    def test_dependent_step_receives_upstream_output(self):
        # step 3 depends on steps 1 and 2 -> its prompt must include their outputs.
        self.config.update(["model=test/m", "execution_agents=3"])
        seen = {}

        def responder(messages, params):
            user = messages[-1]["content"]
            m = re.search(r"step (\d+) of", user)
            seen[m.group(1)] = user
            return f"OUTPUT for step {m.group(1)}"

        runner = self._runner(FakeEngine(responder=responder))
        task = _exec_task(self.tasks, deps=[[], [], [0, 1]])
        runner.run(task, "go")
        self.assertIn("OUTPUT for step 1", seen["3"])
        self.assertIn("OUTPUT for step 2", seen["3"])
        # An independent step does not get other steps' outputs piped in.
        self.assertNotIn("builds on", seen["1"])


class ParallelEndToEndTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tasks = TaskStore(Path(self._tmp.name))
        self.config = ConfigManager()
        self.config.update(["model=test/m", "execution_agents=3"])

    def tearDown(self):
        self._tmp.cleanup()

    def test_orchestrator_step_runs_panel_and_advances_to_validation(self):
        gateway = LLMGateway(FakeEngine(responder=_step_responder))
        base = _RecordingRunner()
        runner = ParallelExecutionRunner(gateway, self.config, base, self.tasks)
        orch = Orchestrator(STAGE_AGENTS, self.tasks, runner)
        task = _exec_task(self.tasks)
        result = orch.step(task)
        # All steps ran in parallel, the stage auto-advanced on the forward edge,
        # and the base runner was never used for execution.
        self.assertEqual(result.advanced_to, "validation")
        self.assertEqual(task["stage"], "validation")
        self.assertEqual(base.calls, [])
        # The transient render/record flags were consumed (never persisted).
        self.assertNotIn("_exec_recorded", task)
        self.assertNotIn("_step_status", task)


class StepTableConcurrencyTest(unittest.TestCase):
    """The live step table must show every concurrently-running step, not just one."""

    def test_render_shows_multiple_in_progress(self):
        from jarvis.repl.commands import render_plan_progress

        task = {
            "plan_steps": ["a", "b", "c"],
            "step_index": 0,
            "_step_status": ["running", "running", "pending"],
        }
        out = render_plan_progress(task)
        self.assertEqual(out.count("▶"), 2)   # two steps in-progress at once
        self.assertIn("(0/3 done)", out)

    def test_render_falls_back_to_step_index_without_status(self):
        from jarvis.repl.commands import render_plan_progress

        out = render_plan_progress({"plan_steps": ["a", "b", "c"], "step_index": 1})
        self.assertEqual(out.count("✓"), 1)
        self.assertEqual(out.count("▶"), 1)


class ReworkLogResetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tasks = TaskStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_reentering_execution_clears_stale_output(self):
        task = self.tasks.new_task("demo")
        task["stage"] = "validation"
        task["plan"] = "p"
        task["stage_outputs"] = {"execution": "[step 1/1] old work"}
        # validation -> execution (rework) must drop the stale execution log.
        self.tasks.advance_stage(task, "execution")
        self.assertNotIn("execution", task["stage_outputs"])

    def test_assemble_deliverable_strips_step_labels(self):
        log = "[step 1/2] first part\n\n[step 2/2] second part"
        self.assertEqual(assemble_deliverable(log), "first part\n\nsecond part")


if __name__ == "__main__":
    unittest.main()
