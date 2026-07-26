# Week 3 — Memory, State and Stateful Agents

**Source:** `transcriptions/03-memory-state-summary.md`,
`transcriptions/03-memory-state-notes-en.md`
**Theme:** Move from scattered messages to a real stateful agent that remembers a
profile, tracks the task stage, honours constraints, and can resume after a pause.

## Stateless vs stateful

- **Stateless agent** answers each request almost from scratch. Signs: no
  long-term context, no user profile, no rules, forgets the global task, skips
  stages, gives roughly one answer to everyone. Example: asked for an auth
  service, it returns a generic Python solution because it does not know the
  project is always Kotlin.
- **Stateful agent** holds state and runs a controlled process. It knows the
  current stage, the profile, the constraints, and the allowed transitions. If
  the rule is "plan first, then code", it will not jump straight to code.

## Personalisation — block 1

Same request should give different answers per user/task. Describe a profile in
three groups:

- **style** — brief vs detailed, formal vs casual, with or without code examples;
- **constraints** — stack, bans, project rules, domain limits;
- **context** — who the user is, why they use the agent, what result they need.

Collect the profile via a start-up interview (onboarding). Personalisation is not
only for code (a language-learning agent needs to know: TOEFL, conversation, or
travel phrases).

Store profile/state in Markdown, a DB, an API store, or vector memory, at
global / per-project / per-repo / per-file scope. Before each turn: identify the
user, load the needed data, inject into the prompt (usually the system prompt).
Do **not** blindly inject everything every turn — it floods context with noise.

## Task state machine — block 2

An agent should be a controlled process, not loose prompt/response. Define: what
counts as a task, its stages, what is saved, which transitions are allowed, and
each stage's inputs/outputs. Typical stages:

```
clarification → planning → execution → validation → done
```

**Allowed transitions** add determinism (e.g. `planning → execution`,
`execution → validation` or back to `planning`, `validation → done` or back to
`execution`). Prompts describing transitions help, but hard bans need **code** —
text rules get lost after summarisation, compaction, or contradictory context.

Save and resume: current stage, approved plan, stage results, profile,
constraints, key task context. After an interruption the agent reloads state and
continues where it stopped.

## Invariants — block 3

Invariants are constraints that must not change turn to turn: stack and
architecture, "Kotlin/KMP/Compose only", "ViewModel required", "no RxJava",
"free APIs only", budget, domain limits. Put them in the prompt **and** check
them in code: filter the model response against the invariant list — no
violations → pass; violation → feedback → redo. It is a linter for
human-language requirements.

## Antipatterns

- Putting everything saved into every prompt.
- Not splitting memory/context into layers.
- Relying on text rules only.
- Not validating state-machine transitions.
- Storing invariants only in Markdown with no code check.
- Letting a random user request break the stack, process, or architecture (the
  LLM wants to help and may agree to violate the process).

## Reference architecture

Request → load profile → load state machine → load invariants → prompt builder →
LLM → validate response → retry/fix on violation → return on pass. Build it
through abstractions: LLM engine, prompt builder, profile storage, task-state
storage, invariant checker, response validator — so any provider plugs in as an
implementation.

## Maps to jarvis-cli

- The FSM is real code: `jarvis/pipeline/fsm.py` — `ALLOWED_TRANSITIONS`,
  `resolve_transition()`; transitions go through `TaskStore.advance_stage`.
- Stores: `jarvis/session/` (thread, task, profile, invariant).
- Invariants: `jarvis/pipeline/invariants.py` with refuse-and-explain.
- Personalisation: onboarding + profile service (see `project_personalisation`).

## Week's assignment

Assemble profile + memory layers + task state machine + invariants + prompt
builder + validation + save/restore into one stateful agent. A good agent comes
from a controlled system, not one long prompt.
