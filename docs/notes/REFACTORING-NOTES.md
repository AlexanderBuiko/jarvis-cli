# KB-Alignment Refactor — Change Notes

Scope: align the implementation with `03-architecture-document.md` (Phases 1–3 of
the audit's migration plan) and fix the high-severity bugs found in
`04-architecture-audit.md`. Working-tree only (no commits). Behavior preserved;
all tests green (**79 passed**, up from 66 — 13 new component tests added).

## What changed

### New components (the God object's responsibilities, given homes)
| Module | Responsibility | Lifted from |
|---|---|---|
| `jarvis/llm/gateway.py` — `LLMGateway` | **Single chokepoint for every model call** + accounting. | scattered `client.complete()` + `make_call_record` across `agent.py` and `invariants.py` |
| `jarvis/pipeline/fsm.py` | FSM policy: `STAGES`, `ALLOWED_TRANSITIONS`, `resolve_transition`. | `session/task_store.py` (repository no longer owns policy) |
| `jarvis/pipeline/runner.py` — `LLMStageRunner` | Runs one stage turn (prompt → model → invariant check → persist). | `JarvisAgent.run_stage_turn` |
| `jarvis/memory/coordinator.py` — `MemoryCoordinator` | All context strategies + summary/facts/topics + **bounded task context**. | `JarvisAgent._build_*`, `_maybe_compress`, `_update_facts`, `_route_to_topic`, … |
| `jarvis/conversation/{state,service}.py` | `ThreadState` dataclass + thread lifecycle. | the 10-field tuple unpacked in 4 places in `agent.py` |
| `jarvis/personalization/service.py` | Profile + behaviour log + nudge + style refinement. | `JarvisAgent` profile/personalize methods |

`JarvisAgent` is now a thin composition-root **facade** (827 → 460 lines): it
wires the services together and delegates. `commands.py`, `loop.py`, and the REPL
keep their stable surface.

### High-severity bugs fixed
1. **Unbounded task context** — the task pipeline sent the full raw transcript
   every turn. `MemoryCoordinator.build_task_context` now bounds it to a recent
   window (the durable task state already rides in the working-memory block).
   Covered by `tests/test_refactor_components.py::MemoryCoordinatorTaskContextTest`.

### Decoupling wins
- The **Orchestrator no longer depends on `JarvisAgent`** — it drives the FSM
  through the `StageRunner` protocol (the old `run_turn` bound-method callback is
  gone). This is the seam the future multi-agent/swarm work plugs into.
- All LLM access funnels through `LLMGateway` (verified: no `.complete()` in app
  code bypasses it), so retries/caching/rate-limiting now have one home.
- FSM policy is independent of persistence and unit-testable on its own.

## What was intentionally deferred (and why)

**Terminal drive-loop extraction** (audit Phase 2: move `_drive_task` /
`_drive_execution` out of `repl/loop.py` into the orchestration layer behind a
presenter, add a `RequestRouter`).

- The orchestrator already owns the FSM stepping; what remains in the REPL is the
  *interactive presenter* (live step table, spinner threading, Ctrl+C semantics,
  Confirm/Reject gates). It is genuinely UI.
- It has **no automated test coverage** and its behaviour can only be verified by
  driving the TUI interactively, which wasn't possible in this unattended run.
  The audit's own Phase-2 risk control was "mitigate with golden-transcript tests
  before moving" — that safety net doesn't exist yet.
- Per "don't risk hard-to-reverse breakage you can't verify," this was deferred
  rather than done blind. **Recommended next step:** add a headless `TaskDriver`
  in `pipeline/` parameterised by a `TaskPresenter` protocol, unit-test it with a
  fake presenter, then make `loop.py` the concrete presenter.

**Per-agent LLM access** (full Phase 3): stage agents still emit/parse strings;
the shared `LLMStageRunner` holds the gateway. This is sufficient for today and
leaves the runner as the swap-in point for a swarmed stage. Giving each agent its
own gateway is only needed once the multi-agent stage is built (the lower-priority
follow-up task).

## Verification
- `python3 -m pytest -q` → **79 passed**.
- Existing FSM / orchestrator / stage-agent / pause-resume tests cover the
  task-pipeline path through the refactored agent unchanged.
