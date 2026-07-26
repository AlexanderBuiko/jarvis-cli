# Validation Swarm — Change Notes (AIAC-18)

Scope: add an agent-swarm validation stage on top of the already-implemented task
FSM. Working-tree only (no commits). Swarm **off** by default — existing behaviour
and all existing tests are unchanged (**107 passed**, up from 92; 15 new tests).

## What the mentor asked for (and how it maps)

> "Create N agents for a stage and have them exchange opinions THROUGH the
> orchestrator agent. They do NOT argue with each other: they offer options to the
> orchestrator agent, which knows the user's request, and it makes a consolidated
> decision. Almost every agent has a bunch of invariants."

- **N reviewer agents**, each a distinct *perspective* with its **own** hard
  invariants (Correctness / Goal fit / Completeness / Robustness / Clarity). Each
  reviews the deliverable against the goal + plan + success criteria
  **independently** and returns pass/fail, concrete issues, and which of *its own*
  invariants it flags. Reviewers never see each other's output.
- **One consolidator (orchestrator) agent** that **knows the user's request**
  (goal, plan, success criteria). It is the *only* place opinions meet; it produces
  one decision — `APPROVE` / `REWORK_EXECUTION` / `REVISE_PLAN` — plus a synthesized
  rationale. It has its own invariants too (e.g. a flagged hard-invariant violation
  forbids APPROVE).

## Where it plugs in (no pipeline rewrite)

`jarvis/pipeline/swarm.py` adds `SwarmStageRunner`, a `StageRunner` (same protocol
the Orchestrator already depends on):

- For **`validation`** (and only when `review_agents` > 1) it runs the panel +
  consolidation and returns the consolidated **text**.
- For **every other stage** it delegates to the wrapped `LLMStageRunner` unchanged.

`JarvisAgent` builds it by wrapping the existing `LLMStageRunner` and injecting it
into the `Orchestrator` — nothing else in the FSM or app changes.

The **`ValidatorAgent` stays the FSM owner** of the validation stage: its input
contract and the 3-way human gate are untouched. The consolidated text carries the
existing markers, so `ValidatorAgent.process` maps it correctly — `REVISE_PLAN`
emits `[[REPLAN]]`, which annotates the gate's "revise the plan" choice as
*(recommended)*. **The human still makes the final 3-way choice**; the swarm only
produces the recommendation.

## Opt-in & bounded

- Config `review_agents` (int, 1–5; default 1 = current single validator). Set via
  `config set review_agents 5`. The panel always runs on a thread pool (reviewers
  are independent, so there's no reason to serialise them); accounting merges in
  panel order so tests stay deterministic.
- **Cost:** ~**N+1** model calls per validation turn (N reviewers + 1
  consolidator). Bounded by the opt-in config; off ⇒ zero extra calls.
- **Single-gateway invariant preserved:** every reviewer and consolidator call goes
  through `LLMGateway`; no `.complete()` bypasses it. Every call is accounted onto
  the task (`api_call_count` / `total_tokens` / `total_cost` via
  `LLMStageRunner._account`), so the swarm's spend shows in `task show` and the
  stage header.

## FSM guarantees (verified, unchanged)

- Valid states + permitted transitions remain in `jarvis/pipeline/fsm.py`; all
  transitions still go through `TaskStore.advance_stage` (the LLM never
  self-transitions). The swarm produces a *recommendation*, not a transition.
- "Can't skip a stage" and pause/resume still hold (existing tests green). An
  illegal transition on the user-reachable `advance_to` path now surfaces cleanly
  (returns `None`, FSM stays put) instead of crashing the REPL — see
  `tests/test_pause_resume.py::test_illegal_transition_is_handled_gracefully`.

## Tests (`tests/test_validation_swarm.py`, FakeEngine, no network)

- one reviewer's opinion parsing (verdict / issues / **own** invariant ids only);
- the consolidator aggregating opinions into each of the 3 decisions + correct
  marker (and the safe `REWORK` default on an unparseable reply);
- the swarm runner delegating non-validation stages (and swarm-off validation) to
  the base runner;
- an end-to-end validation-with-swarm via `Orchestrator.step` producing the right
  gate verdict (`replan_recommended` on `REVISE_PLAN`, not on `APPROVE`);
- a per-agent invariant flag surfaced in the consolidation;
- per-task accounting accumulation across all swarm calls (sequential & concurrent).

## Verification

- `python3 -m pytest -q` → **107 passed**.

---

# Follow-up (AIAC-18b) — reviewer tuning, rework convergence, parallel execution

Three changes after exercising the swarm on a real task. Suite: **121 passed**.

## 1. Reviewer invariants were too strict / off-target

On a "beginner pasta tutorial" the Robustness reviewer kept *inventing* unstated
requirements (altitude, hard water, gluten-free…) and Clarity kept failing on the
execution **work-log scaffolding** (`[step 1/6]` labels + intermediate drafts). A
bad reviewer output is a candidate for a tighter invariant, so:

- Every reviewer now gets a global rule: *judge ONLY against the stated goal +
  success criteria; never invent requirements/edge cases; ignore process scaffolding
  (assembled at the done stage).*
- **Robustness** fails only on constraints/edge cases **explicitly stated** by the
  user (dropped the speculative "obvious failure mode" rule).
- **Clarity** judges the content's substance for its intended reader, not bookkeeping.

## 2. Rework couldn't converge (the real bug behind "rework changes nothing")

`ExecutorAgent.record` *appends* each step to `stage_outputs["execution"]` and never
reset it, so reworking execution piled more onto the old log and validation re-read
an ever-growing, multi-version document. Fixes:

- `TaskStore.advance_stage` clears `stage_outputs["execution"]` whenever execution is
  (re)entered — a rework now produces a fresh deliverable.
- The swarm reviews the **assembled** deliverable: `assemble_deliverable()` strips the
  `[step k/n]` labels so reviewers see one continuous result, not the work-log.

## 3. Parallel execution (opt-in, planner-marked dependencies)

`jarvis/pipeline/parallel.py` — `ParallelExecutionRunner` (a `StageRunner` on the
same seam). For `execution` with `execution_agents` > 1 it runs the plan's steps with
a pool of executor agents, honouring the dependency graph:

- `PlannerAgent` annotates each step `[after: <step numbers>]` / `[after: none]`;
  `parse_plan()` parses it into `plan_deps` (sanitised to earlier steps ⇒ no cycles).
- `execution_waves()` groups steps into topological waves; steps **within** a wave run
  concurrently (`ThreadPoolExecutor`, bounded by `execution_agents`), waves in order.
  Dependent steps receive their upstream outputs.
- The runner writes the assembled output, accounts every call onto the task, sets a
  transient `_exec_recorded` flag so `ExecutorAgent.record` doesn't re-append, and
  emits `[[READY]]` ⇒ orchestrator advances `execution → validation`. **The FSM is
  untouched.**

Config: `execution_agents` (int 1–8, default 1 = today's sequential behaviour).
Cost: one model call per step (same as sequential), just overlapped — bounded by the
opt-in. Off by default; legacy/un-annotated plans treat every step as independent.

**Caveat:** correctness of parallelism depends on the planner's `[after: …]`
annotations being right; a missed dependency could run a step before its input. The
annotations are the contract.

**Live step table:** the runner publishes `task["_step_status"]`
(pending/running/done, pre-sized so only GIL-atomic element writes happen under
concurrency) and `render_plan_progress` prefers it, so the REPL shows every
concurrently-running step as ▶ at once — not just the first step until the whole
stage finishes. `ExecutorAgent.record` pops it (with `_exec_recorded`) so it's never
persisted.

Wiring (`jarvis/agent.py`): `LLMStageRunner` → `SwarmStageRunner` (validation) →
`ParallelExecutionRunner` (execution) → `Orchestrator`. Each overrides one stage and
delegates the rest.

New tests: `tests/test_parallel_execution.py` (plan-dep parsing, topological waves,
delegation when off, per-step run + READY, accounting, upstream-output passing,
end-to-end advance to validation, rework-log reset, deliverable assembly).
