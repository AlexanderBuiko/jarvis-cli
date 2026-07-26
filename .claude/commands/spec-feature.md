---
description: Interview me about a feature, write a spec, then run the full pipeline
---

Adapted for **jarvis-cli** from the mentor's `spec-interview-command` (originally
written for a Java/Spring/Vue stack). Rewired to this project's real agents, FSM
stages, and commands. Read `$ARGUMENTS` as the raw feature request.

This runs the full task lifecycle from `CLAUDE.md`:
`clarification → planning → execution → validation → done`. State the current and
next stage before every transition. Only legal transitions (forward; `validation`
→ `execution`/`planning`; `execution` → `planning`).

## Step 1 — Study the codebase BEFORE interviewing (clarification)

Investigate the existing code first, so questions are concrete, not abstract.
In parallel where possible:

1. Read `CLAUDE.md` and `docs/conventions.md` — stack, patterns, invariants.
2. Read the relevant lecture in `docs/lectures/` if the feature maps to a course
   topic (RAG, MCP, local LLM, pipeline…).
3. Locate similar existing code with Grep/Glob — find features, Protocols, stores
   that resemble the request.
4. Read the 2–4 most relevant files (a REPL command, a store, a pipeline stage) to
   learn the local dialect.
5. Identify integration points: which packages the feature touches
   (`repl/`, `llm/`, `pipeline/`, `mcp/`, `indexing/`, `rag/`, `session/`,
   `config/`) and the registration points a new command/param/tool needs.

Delegate broad reading to the `Explore` or `planner` agent so the transcript stays
out of the main context. Form a short internal picture: what exists, which patterns
are used, where the feature fits.

## Step 2 — Deep interview (clarification)

Interview me through **AskUserQuestion**. Questions must be:

- **Concrete** — reference real files, Protocols, stores from the code
  ("store in the existing `TaskStore` JSON, or a new store?").
- **Non-obvious** — do not ask what the code or request already answers.
- **Architectural** — trade-offs, risks, compatibility with the layering rule
  (library packages must not import `repl/` or print).
- **UX/CLI** — command shape, autocomplete, edge cases, interaction with existing
  REPL verbs.

Cover: implementation, CLI/UX, security (MCP tools, secrets), invariants,
trade-offs, risks, backward compatibility. Keep interviewing until it is complete.

## Step 3 — Write the spec (planning)

Write the spec to `.specs/<feature-slug>.md` (create `.specs/` if absent). Include
everything from the interview + codebase context: existing patterns to reuse,
integration points, files to touch, the registration checklist, and which
invariants/antipatterns apply.

## Step 4 — Run the full pipeline, spec as the request

Announce each stage transition. Use this project's agents (`.claude/agents/`),
which mirror the app's own pipeline roles:

1. **planning** — run `planner` (read-only) to produce a numbered, ordered plan
   naming every file to touch and every registration point. For a
   larger/architectural feature, also run the `Plan` agent for trade-offs. Present
   the plan; I approve before any edit.
2. **execution** — run `executor` to implement the approved plan step by step,
   following `CLAUDE.md` conventions. If reality contradicts the plan, stop and
   go back to `planning`.
3. **validation** — run `validator`, which runs the real checks and reports actual
   output:
   - `.venv/bin/python -m pytest -q`
   - `.venv/bin/ruff check jarvis/` (baseline = 5 pre-existing errors; only new
     ones count)
   - `.venv/bin/python -c "import jarvis.repl.loop"`
   - if a command/flag/behaviour changed, invoke the `update-smoke` skill and
     rerun `python scripts/qa_report.py`.
   On failure, go back to `execution`. Tests ship with the change (invariant 6).
4. **review (optional, on validation)** — for a risky change, run several
   `reviewer` agents in parallel with different perspectives (they never see each
   other), then one `consolidator` that knows the goal merges their opinions into
   APPROVE / REWORK_EXECUTION / REVISE_PLAN. Route defects back, not forward.
5. **done** — one-line report: what changed, what was verified (with real
   output), what was deferred. Nothing reaches `done` unvalidated.

## What was dropped from the mentor's original

`ast-index` (this repo has no AST index MCP), the Java/Vue/Spring agents
(`java-architect`, `vue-expert`, `ui-designer`, `builder-spring-feature`,
`builder-compose-feature`), the "Бизнес-фича" profile name, and the fixed
6-agent research council — replaced by this project's `planner`/`executor`/
`validator`/`reviewer`/`consolidator` agents and its `pytest`/`ruff`/import
checks.
