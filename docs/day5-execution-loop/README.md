# Day 5 — Execution Loop

Run the assistant unattended over a pool of tasks: **take a task → run → commit →
take the next**, no human between tasks. Measure how far it gets, tune, rerun, and
compare cloud vs local.

This folder contains everything to reproduce it:

| File | What it is |
|---|---|
| `task-pool.md` | The tracker: 18 tasks (bugs, features, refactors, tests, docs, research), each with a done/not-done criterion. |
| `sandbox-seed/` | A throwaway `calckit` project the tasks operate on (seeded with the defects the tasks fix). |
| `RESULTS-template.md` | Where you paste the metrics from your runs. |

There are **two vehicles**, on purpose:

1. **Claude Code harness** (the `execution-loop` skill) — the **graded** deliverable:
   the tuned code assistant running full-cycle, unattended. Two passes (before /
   after tuning). See *Harness run* below.
2. **jarvis `task loop`** — a real jarvis feature
   ([`jarvis/pipeline/loop.py`](../../jarvis/pipeline/loop.py)), used for the
   **cloud-vs-local** leg, since only jarvis swaps the backing model cleanly
   (OpenRouter ↔ Ollama). Everything from "Run 1 — cloud" onward is this vehicle.

---

## Harness run (Claude Code) — the graded deliverable

The metric is **how many tasks finish in a row without the loop stopping.** Run it
in a fresh, isolated scratch copy of the sandbox so unattended commits never touch
this repo.

**1. Build the scratch sandbox (with the harness config + a self-validating venv):**

```bash
SANDBOX=$(mktemp -d /tmp/loop.XXXX)
cp -R docs/day5-execution-loop/sandbox-seed/. "$SANDBOX"/
mkdir -p "$SANDBOX/.claude/skills"
cp -R .claude/agents "$SANDBOX/.claude/agents"           # planner/executor/validator/…
cp -R .claude/skills/execution-loop "$SANDBOX/.claude/skills/execution-loop"
cp docs/day5-execution-loop/task-pool.md "$SANDBOX/task-pool.md"
cd "$SANDBOX"
python3 -m venv .venv && .venv/bin/pip install -q pytest  # the validator's pass/fail gate
git init -q -b main && git add -A && git commit -qm seed
echo "sandbox = $SANDBOX"
```

**2. Pre-authorise tools so the loop never stops for permission.** Create a tiny
allow-list in the scratch sandbox (this is the "rigid boundaries" step — cleaner
than `--dangerously-skip-permissions`, which is the quick alternative for a
throwaway dir):

```bash
cat > "$SANDBOX/.claude/settings.local.json" <<'JSON'
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
      "Bash(.venv/bin/python -m pytest *)",
      "Bash(git *)", "Bash(date *)", "Bash(mkdir -p *)"
    ]
  }
}
JSON
```

**3. Start a fresh session in the sandbox and hand it one instruction:**

```bash
cd "$SANDBOX" && claude
```
then type:
> run the execution loop over `task-pool.md`

Walk away. The skill cuts a branch per task, runs planner→executor→validator,
commits, merges back on green, and appends a metric row to
`./harness-runs/run-<timestamp>.md`.

**4. Collect the metrics** when it finishes/stops:
- the **run-log** `harness-runs/run-*.md` — streak, per-task outcome, rework, time,
  where it broke;
- the **token/cost** from Claude Code itself (`/usage` or the session cost line) —
  the loop does not self-report tokens.

**5. Verify by hand:**
```bash
cd "$SANDBOX" && git log --oneline && .venv/bin/python -m pytest -q
```

**6. Tune and run pass 2.** Read "broke on → why", make the smallest fix (task
wording / a model tier in `.claude/agents/*` / a rule), rebuild the scratch
sandbox, rerun. The delta pass 1 → pass 2 is the headline result.

Record both passes in `RESULTS-template.md`.

---

## What "execution loop" means here

The pipeline is normally interactive — it pauses at every gate (a clarification
question, plan approval, the final done decision). `task loop` is the **headless**
driver: it resolves those gates by policy so a whole pool runs with no keyboard.

Gate policy (`ExecutionLoop` in `jarvis/pipeline/loop.py`):

| Gate | Autonomous decision |
|---|---|
| Clarification question | Answer "proceed with sensible defaults". After `max_questions` (2) unanswered rounds → task is **STUCK** (did not understand from context). |
| Plan approval | Auto-confirm → execute. |
| Validation (done decision) | Confirm **done** — unless the validator flagged a failure (`[[FAIL]]`/`[[REPLAN]]`), then rework/replan, bounded by `max_reworks` (2). Exceeding it → **FAILED** (non-working result). |
| Turn cap (`max_turns` 60) | → **HUNG** (looping). |

After each task the loop **commits the sandbox** (`--allow-empty`, one commit per
task, message `[outcome] task name`), so `git log` is a second copy of the
execution log.

### On "the assistant selects the profile (Bug Fix / Research / feature)"

jarvis does **not** switch discrete profiles per task — it has one FSM pipeline
(`clarification → planning → execution → validation → done`) that adapts to the
request. So instead of routing to a profile, the loop tags each task with its
kind (`[bug]`, `[research]`, …) and puts that tag in the request, and it records
the kind in the metrics. A `[research]` task, for example, produces a written
answer and its validation checks "analysis only, no code change". This is the
project's equivalent of profile selection; the metric table shows per-kind
behaviour. (If you want true per-kind tuning, that is a follow-up: branch the
generation params by `spec.kind` before each task.)

---

## Metrics captured (per the assignment)

Written to `<sandbox>/.jarvis-loop/run-<provider>-<timestamp>.md` (+ `.jsonl`) and
printed at the end:

- **Streak** — tasks finished in a row from the start before the first break.
- **Broke on** — the first task that did not finish, and **why** (stuck / failed /
  hung / blocked).
- **First-pass rate** — share of tasks that reached done with zero rework.
- **Average time per task.**
- Per task: outcome, stage reached, wall time, provider requests, cost, rework
  count, commit sha.

---

## Prerequisites

- A working `jarvis` (`.venv/bin/pip install -e .` from the repo root).
- **Cloud run:** `OPENROUTER_API_KEY` in `~/.jarvis/.env` (or the environment).
- **Local run:** [Ollama](https://ollama.com) running with a model pulled, e.g.
  `ollama pull qwen2.5:7b`.

---

## Run 1 — cloud

Everything below is copy-paste. It keeps the loop's commits **out of** the
jarvis-cli repo by working in a scratch copy of the sandbox.

**1. Make a scratch sandbox and point the file tools at it.**

```bash
SANDBOX=$(mktemp -d /tmp/calckit.XXXX)
cp -R docs/day5-execution-loop/sandbox-seed/. "$SANDBOX"/
git -C "$SANDBOX" init -q && git -C "$SANDBOX" add -A && git -C "$SANDBOX" commit -qm "seed"
export JARVIS_FILES_ROOT="$SANDBOX"
echo "sandbox = $SANDBOX"
```

**2. Launch jarvis and set it up for unattended writes.** Writes MUST be
pre-authorised or the loop can't edit files (they'd queue for approval that never
comes):

```
config set file_writes auto
```

**3. Run the loop** (from inside jarvis; the pool path is relative to where you
started jarvis — use an absolute path if unsure):

```
task loop docs/day5-execution-loop/task-pool.md --sandbox <paste $SANDBOX here>
```

Watch the per-task lines scroll (`✓ done` / `✗ failed …`). At the end it prints
the metrics table and the log path. Tip: `task loop <pool> --dry-run` first to
confirm the 18 tasks parse without spending a single API call.

**4. Record the metrics** into `RESULTS-template.md` (Run 1 / cloud column).

---

## Verify with your own hands

Nothing here is on trust — check it directly:

```bash
# 1. The commits: one per task, outcome in each message.
git -C "$SANDBOX" log --oneline

# 2. The code actually changed and still works.
cd "$SANDBOX" && python -m pytest -q ; cd -

# 3. The metrics log the loop wrote.
cat "$SANDBOX"/.jarvis-loop/run-*.md

# 4. Spot-check a fix by hand, e.g. the divide-by-zero bug (task 1):
cd "$SANDBOX" && python -c "from calckit.core import divide; print(divide(1,0))" ; cd -
# expected: None
```

If a task is marked `done` but the code is wrong, that is a **first-pass=✗** or a
validator miss — note it; that is exactly the kind of "fall" the assignment wants.

---

## Tune, then Run 2

Look at where Run 1 broke and why, then make the **smallest** change that
addresses it and rerun the same pool. Typical levers:

- **Task wording** — a `stuck` task usually means the criterion was ambiguous.
  Tighten that line in `task-pool.md` (this is the "refine the rules" step).
- **Rework budget** — a `failed` task that was close may just need more retries:
  bump `max_reworks` (in `ExecutionLoop`'s construction in
  `jarvis/repl/loop.py::_run_execution_loop`).
- **Invariants / system prompt** — if the model keeps asking to clarify, sharpen
  the clarifier's "choose sensible defaults" instruction, or the global
  invariants file (`invariants` command).
- **Generation params** — `config set temperature 0.2` for steadier execution.

Reset the scratch sandbox to the seed before Run 2 so the comparison is fair:

```bash
git -C "$SANDBOX" reset --hard seed 2>/dev/null || { rm -rf "$SANDBOX"; SANDBOX=$(mktemp -d /tmp/calckit.XXXX); cp -R docs/day5-execution-loop/sandbox-seed/. "$SANDBOX"/; git -C "$SANDBOX" init -q && git -C "$SANDBOX" add -A && git -C "$SANDBOX" commit -qm seed; export JARVIS_FILES_ROOT="$SANDBOX"; }
```

Record Run 2. Compare: how many more tasks in a row did it last?

---

## Local model run

Same pool, local model, to see how many it pulls out:

```
config set provider ollama
config set model qwen2.5:7b
```

Reset the sandbox (as above), then `task loop …` again. The log filename carries
the provider, so cloud and local runs don't overwrite each other. Fill the local
column in `RESULTS-template.md`.

---

## Deliverable checklist

- [x] Pool of 15–20 tasks → `task-pool.md` (18).
- [ ] Execution log (task → result → time) → the `.md`/`.jsonl` under
      `<sandbox>/.jarvis-loop/`, plus `git log`.
- [ ] "How many in a row without a pause" in two runs → `RESULTS-template.md`.
- [ ] Cloud vs local comparison → `RESULTS-template.md`.
