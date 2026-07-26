---
name: execution-loop
description: Run a pool of tasks unattended, full-cycle, one after another — take a task, run plan→execute→validate→commit, record a metric, take the next. Use when the operator hands you a task-list file and says "run the execution loop" (Week-8 harness deliverable). The score is how many tasks finish in a row without the loop stopping.
---

# Execution loop

You are the **orchestrator**. Your job is to route, not to do the work: for each
task you spawn subagents, gate their output, commit, and move on. You do **not**
prompt the operator between tasks — they started this in a fresh session and left.

The metric is: **how many tasks finish in a row without the loop stopping.** A loop
stops for exactly three reasons, and this recipe is built to remove all three:

1. **Permission prompt** — boundaries too loose. The allow-list in
   `.claude/settings.local.json` must already cover git, ruff, pytest and edits.
   If a tool still prompts, that task is a stop: log it and continue.
2. **Clarification** — context insufficient. In loop mode you **never ask**. If a
   task is ambiguous, choose the most reasonable interpretation, note the
   assumption in the commit body, and proceed. Only if it is impossible to make
   any reasonable attempt do you log the task FAILED and continue.
3. **Error / hang** — no validation or retry. The validator subagent + a bounded
   retry (below) handles this.

## Inputs (state them back before starting)

- **Task pool file** — one task per markdown list item, optional `[bug]` /
  `[feature]` / `[refactor]` / `[test]` / `[docs]` / `[research]` tag. If the
  operator did not name one, use `docs/day5-execution-loop/task-pool.md`.
- **Base branch** — default `main`. Each task runs on its **own** branch cut from
  the latest base; on success it merges back, so the next task starts from the
  updated code. This keeps history atomic and prevents two tasks touching the
  same file (each starts from a clean, current base).
- **Retry budget** — default 2 rework cycles per task.

If an input is missing, pick the stated default and say so — do not stop to ask.

## Model tiers (token economy — the Week-8 point)

Do not run opus for everything. The subagents are already tiered in
`.claude/agents/`:

| Role | Model | Why |
|---|---|---|
| orchestrator (you) | opus | routing + judgment only |
| planner | sonnet | structured plan, not deep reasoning |
| executor | sonnet | capable at code; bump to opus only for a task that failed on sonnet |
| validator | haiku | just runs ruff/pytest and reports output |
| reviewer / consolidator | sonnet | bounded, single-perspective work |

Keep your own context lean: read subagent **reports**, not their transcripts.
Never do a task's editing yourself in the main context — always via `executor`.

## Per-task procedure

For each task, top to bottom, sequentially:

1. **Record start + branch.** `date +%s` for the wall-clock start. Cut a fresh
   branch off the latest base: `git switch <base> && git pull --ff-only 2>/dev/null;
   git switch -c loop/<n>-<slug>`. Note the task's declared kind.
2. **Select the profile** from the kind: `[bug]`→bug-fix, `[research]`→research,
   everything else→feature/default. (`~/.claude/profiles/`.)
3. **Plan** — spawn `planner` with the task text. Get the ordered plan + files.
4. **Execute** — spawn `executor` with the approved plan. It edits files.
5. **Validate** — spawn `validator`. It runs the **target project's** own checks:
   - **calckit sandbox** → `.venv/bin/python -m pytest -q` from the sandbox root
     (the sandbox's `.venv` has pytest; calckit imports from the cwd). No ruff.
   - **jarvis-cli** → `.venv/bin/ruff check jarvis/` (baseline is 5 pre-existing
     errors — only new ones count), `.venv/bin/python -m pytest -q`, import check.
6. **Gate on the validator's report:**
   - **Pass** → go to commit.
   - **Fail, within retry budget** → spawn `executor` again with the validator's
     exact output as feedback. Re-validate. (This is the conditional routing loop.)
   - **Fail, budget exhausted** → the task is `FAILED` (non-working result).
     Commit what exists so the state is captured, then move on.
7. **Review (risky tasks only)** — for a task touching a security boundary,
   permissions, or the FSM, run 2–3 `reviewer` subagents in **parallel** with
   different perspectives, then one `consolidator`. Skip for routine tasks; it
   costs N+1 calls. This is the only stage that runs in parallel.
8. **Commit** — one commit on the task branch: `git add -A && git commit -m
   "[<outcome>] <task>"`. Put any assumption you made in the commit body.
9. **Merge back — only if validation passed.** `git switch <base> && git merge
   --no-ff loop/<n>-<slug>`. If the task FAILED, do **not** merge: leave the branch
   for the operator to inspect, switch back to base, and continue. The next task
   cuts its branch from this now-updated base. (Merging validated work to `<base>`
   unattended is the one real risk — the validator gate is what makes it safe. For
   an audit trail, push the branch and open a PR instead of a local merge.)
10. **Record end** (`date +%s`) and append a metric row (format below).
11. **Next task.** Do not summarise to the operator between tasks.

## Outcomes (classify every task as one)

| Outcome | Meaning |
|---|---|
| `done` | validator passed |
| `done-first-pass` | validator passed with zero rework cycles |
| `failed` | validator never passed within the retry budget (non-working) |
| `stopped` | the loop had to pause — a permission prompt, or a genuine block |
| `hung` | a subagent did not return / a step could not complete |

The **streak** is the count of consecutive `done`/`done-first-pass` from the start
before the first non-done task.

## Metric log

Write to `./harness-runs/run-<YYYYMMDD-HHMMSS>.md` in the run directory
(create the dir). **Append after each task** so a crash still leaves the log.
One table, then a summary block at the end:

```
| # | task | kind | profile | outcome | rework | time(s) | commit |
|---|------|------|---------|---------|--------|---------|--------|
| 1 | ...  | bug  | bug-fix | done-first-pass | 0 | 41 | a1b2c3d |
```

Final summary:

```
## Summary
- streak (in a row): N / TOTAL
- completed: N / TOTAL
- first-pass rate: NN%
- avg time/task: NNs
- broke on: '<task>' (<outcome>) — <why>
- model tiers: orchestrator=opus, planner/executor/reviewer/consolidator=sonnet, validator=haiku
```

**Do not invent token counts.** Claude Code does not report per-task tokens to you;
read total usage from Claude Code's own usage view after the run and add it to the
results write-up by hand. Report only what you measured: outcomes, retries, time.

## After the loop

Print the summary block to the operator (this is the one time you address them),
and name the run-log path. Do not clean up the branch/worktree — the operator
inspects the commits and the diffs to verify.

## Context hygiene (why the loop stays cheap over many tasks)

The token cost of a long loop is dominated by what the **orchestrator** carries.
Keep it minimal:

- **Do the work in subagents.** Each subagent has its own context window; when it
  returns, that window (its file reads, diffs, test output) is discarded and only
  its short report reaches you. So a task's heavy context dies with the task — it
  does not accumulate across the pool. Never read files or run edits in the main
  context to "save a round trip"; that is exactly the context you do not want to
  keep.
- **Keep only the metric line per task**, not the reports. State lives on disk —
  git holds the code, the run-log holds the metrics — so nothing task-specific
  needs to survive in the window.
- **For maximum hygiene, one session per task.** Because state is on disk, a fresh
  session (or `/clear`) between tasks costs nothing: the new session needs only
  the task text + the repo at its current commit. This pairs with branch-per-task
  — new branch, new session, empty orchestrator, appends to the same run-log.
  Each task then has the *necessary and sufficient* context and no more.

## Boundaries (why the loop can run unattended)

- The allow-list in `.claude/settings.local.json` pre-authorises git, ruff,
  pytest, python, and file edits, so no step waits on a permission prompt.
- The "never ask in loop mode" rule above removes the clarification stop.
- The validator + bounded retry removes the silent-broken-code stop.
  Tighten the task wording in the pool file (not the prompt) when a task keeps
  stopping — that is the "refine the rules, rerun" step of the assignment.
