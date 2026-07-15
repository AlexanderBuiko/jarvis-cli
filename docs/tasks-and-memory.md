# Jarvis CLI — Tasks, Memory & Context

Chat and tasks are two separate surfaces. Threads are pure conversation; a task is a
standalone workspace with its own context and a code-enforced lifecycle.

## The task pipeline

A task moves through explicit stages, enforced in code (not prompt text):

```
clarification → planning → execution → validation → done
```

- **Orchestrator + FSM** (`jarvis/pipeline/orchestrator.py`, `fsm.py`) — track the
  current stage, permit only allowed transitions, and forbid stage-skipping. There
  is an `execution → planning` edge for re-planning, and `validation → execution`
  for rework.
- **Stage agents** (`stages.py`, driven via a `StageRunner` seam) — each stage runs
  its own agent over the `LLMEngine`/invariant abstractions, receiving only its
  slice of the task.
- **Pauses** — the pipeline pauses only when it needs you: a free-text question
  (clarification, or an execution step needing input) or a Confirm/Reject choice at
  the two critical gates (plan approval and the final done decision).
- **Autonomous run** — `task run` continues the entered task with no new input; the
  default is to run stages automatically until a pause is required.

### Parallel execution and the validation swarm

- `execution_agents` > 1 runs independent plan steps concurrently in topological
  "waves", ordered by planner-marked `[after: …]` dependencies (a live step table
  shows concurrency).
- `review_agents` > 1 turns the validation stage into an independent reviewer swarm:
  N reviewers each with their own invariants feed a consolidator (which knows the
  goal), whose recommendation goes through the unchanged validator's three-way gate.

### Results

At `done` a short summary is shown, the full deliverable is written to a result
file, the task is exited, and its result is attached to the current thread — so the
chat that follows is enriched by the task's output. `task attach` / `task detach`
manage attachments manually.

## Context strategies (per thread)

`context_strategy` controls how a long conversation is kept within budget:

- `none` — full history sent verbatim (default).
- `compression` — a rolling summary replaces older turns.
- `sliding_window` — only the most recent N turns (`window_size`).
- `sticky_facts` — a structured facts block prepended to history.
- `dialogue_state` — a Goal/Given/Constraints "task memory" block kept and updated
  each turn (pairs well with `rag on` for a grounded mini-chat). See `thread state`.
- `topics` — automatic topic routing; context scoped per topic.

These are mutually exclusive and can only be changed on an empty thread.

## Memory layers

Jarvis models memory explicitly (`jarvis/memory/coordinator.py`): short-term
(session messages), working memory (the task with its code-enforced state machine),
and long-term memory (Markdown injected into the system prompt). Facts are extracted
periodically; conversations can branch, forking from the current state.

## Invariants (global hard rules)

`invariants.md` (`~/.jarvis/memory/invariants.md`, scaffolded by `invariants init`)
is the single, app-wide hard-rule file. It is injected into every prompt **and**
enforced in code: when a request conflicts with an invariant, the agent refuses,
names the invariant, and explains why.

## Profile (personalisation)

`profile.md` is system-managed: created by `profile onboard` (a short interview:
style, constraints, context) and injected into every prompt. `personalize` proposes
an update to only the profile's `## Style` section from recent behaviour, showing
current vs proposed and asking before overwriting. Personalisation is single-user
and ephemeral (propose + confirm), never silently applied.
