# Day-5 execution-loop results

Runs 1–2 are the **Claude Code harness** (the graded deliverable; logs in
`harness-runs/`). Run 3 is the **local** leg via jarvis `task loop` (Ollama; log in
the sandbox's `.jarvis-loop/`).

## Headline — how many in a row without a pause

| Run | Assistant / model | Streak (in a row) | Completed | First-pass % | Avg time/task | Broke on → why |
|-----|-------------------|-------------------|-----------|--------------|---------------|----------------|
| 1 — cloud, before tuning | Claude Code harness: opus orchestrator, planner/executor **sonnet**, validator **haiku** | **18** | 18 / 18 | **100%** | ~91s wall (≈50s API) | none — full pool cleared. Caveat: validator (haiku) flaked once on task 5 (misread the diff as "no changes"); orchestrator fell back to running `pytest` directly |
| 2 — cloud, after tuning  | same, validator → **sonnet** (confirmed: haiku ≈0 tokens) | **18** | 18 / 18 | **100%** | 63s (≈70s wall) | none — **validator flake gone** |
| 3 — local                | jarvis `task loop`, `qwen2.5:7b` (Ollama) | **1** | 5 / 18 | 22% | 77s (~23m total, $0) | task 2 (`mean([])`) — stuck, clarification loop |

### Run 1 session facts (from Claude Code `/usage`)
- **Cost:** $3.95 (sonnet $3.88, haiku $0.074)
- **Duration:** 27m20s wall · 14m52s API
- **Code changes:** +176 / −28 lines
- **Tokens:** sonnet 5.6k in / 56.3k out / 6.4M cache-read / 240.6k cache-write; haiku 1.2k in / 7.5k out / 156.5k cache-read
- **Honesty note:** 3 of the 18 (tasks 10, 13, 14) were no-ops — already satisfied by earlier tasks' fixes — recorded as done with an empty commit. So ~15 tasks did real work.

### Run 2 session facts (validator → sonnet)
- **Cost:** $5.37 (sonnet $5.37; **haiku $0.0012 — 26 output tokens, proving the
  validator moved off haiku onto sonnet**). The run-log's "validator=haiku" line is
  stale skill boilerplate, not what ran.
- **Duration:** 21m10s wall (faster than Run 1's 27m20s) · 19m41s API (slower —
  sonnet validation does more work per task).
- **Code changes:** +209 / −28 lines
- **Tokens:** sonnet 6.5k in / 87.7k out / 8.2M cache-read / 355.8k cache-write.
- **Timing:** Run 2's per-task times are real (22–107s, avg 63s); Run 1's were not
  measured. Use Run 2's for the "time/task" figure.

## What I changed between Run 1 and Run 2

- **Fall in Run 1:** the haiku validator misreported a real diff as "no changes" on
  task 5 (the one reliability wobble in the run).
- **Change:** moved the validator subagent from haiku → sonnet (`.claude/agents/validator.md`).
  Rationale: the validator's job is mechanical (run the tests, report the pass
  count), but haiku misread the change; sonnet is steadier for the same cost tier
  as the other agents. Rebuild the scratch sandbox before Run 2 so the copied
  `.claude/agents/` picks up the new tier.
- **Actual effect (measured):**
  - Streak unchanged: **18/18 → 18/18**. The pool is not hard enough to differentiate
    streak — both runs hit the ceiling. The tuning value showed up in *reliability*,
    not in the headline count. (To make streak itself move, the pool would need
    harder / more interdependent tasks.)
  - **The validator flake is gone** — no misreported diff in Run 2. That is the real
    before/after result.
  - **Cost rose: $3.95 → $5.37 (+36%)**, and API time 14m52s → 19m41s, from the sonnet
    validator + more sonnet output (56k → 88k). This is the token-economy price of the
    reliability fix, and Claude Code's own usage panel flagged it ("consider a cheaper
    model for simpler subagents").
  - **Verdict / next lever:** for a mechanical check, the cheaper root-cause fix is to
    put the validator *back* on haiku but instruct it to **run `pytest` and report the
    pass count, never infer pass/fail from a prose diff** — that removes the flake
    without the +36% cost. Sonnet is the safe choice; haiku-plus-discipline is the
    economical one.

## Cloud vs local

- **Streak: cloud 18 in a row vs local 1.** Local (`qwen2.5:7b`) completed 5/18
  total, first-pass 22%, and broke on task 2. The very first task passed, then the
  model stalled.
- **Where local fell short:** not the tasks — the **pipeline-driving**. The 7B
  model kept emitting `[[NEEDS_USER]]` (asking for clarification it was told not to)
  or never emitted a terminal marker, so tasks ended `stuck` in clarification /
  execution. Two tasks ground against the turn cap (task 4: 269s/44 reqs, task 11:
  203s) without converging.
- **Not an apples-to-apples model test — state this plainly:**
  - *Different validation bar.* Cloud "done" = **`pytest` actually passed** (real
    verification). Local "done" = the jarvis pipeline's **LLM-judged** validation,
    no pytest gate — a **weaker** bar. So local's 5/18 is generous; the code was not
    independently verified, and some of the 5 were the trivial/no-op tasks.
  - *Different assistant, not just model.* Cloud = the tuned **Claude Code harness**
    (opus orchestrator + sonnet subagents, marker-free tool use). Local = the
    **jarvis pipeline** (single loop, marker protocol) on a 7B model. So this
    measures "tuned cloud harness" vs "local model in jarvis", not model-A vs model-B
    in the same harness.
  - *File-root leak (run-harness bug).* The local run's file writes landed in the
    process cwd instead of the sandbox (`JARVIS_FILES_ROOT` did not reach the
    file-server subprocess), so the sandbox's per-task commits were empty and the
    "done" tasks were judged without their edits in place. This makes the local
    5/18 softer still — a harness bug, not a model limitation. Follow-up: verify the
    env reaches the file server before trusting local `task loop` metrics.
- **Cost / speed:** cloud $5.37 & ~21m wall; local **$0** & ~23m wall. Local is free
  and comparably slow, but pulls out a fraction of the work at a lower bar of proof.
- **Takeaway:** a small local model is viable for single, well-scoped edits, but
  cannot sustain an unattended multi-task loop that depends on strict
  instruction-following. The harness's reliability comes from strong
  instruction-followers (opus/sonnet) at the wheel — exactly the week's thesis about
  how rigidly the boundaries can be enforced.

## Per-task detail

### Run 1 (cloud, before tuning) — `harness-runs/run1-cloud-20260726-234532.md`

```
| # | task | kind | outcome | rework | commit |
|---|------|------|---------|--------|--------|
| 1 | divide returns None on b=0            | bug      | done-first-pass | 0 | ed5dd5a |
| 2 | mean([]) returns 0.0                  | bug      | done-first-pass | 0 | cbef34e |
| 3 | slugify lowercases output            | bug      | done-first-pass | 0 | 5632f94 |
| 4 | median averages two middle values    | bug      | done-first-pass | 0 | a4b6071 |
| 5 | add power(base, exp)                 | feature  | done-first-pass | 0 | 616ed68 |
| 6 | add clamp(value, low, high)          | feature  | done-first-pass | 0 | 35d34dc |
| 7 | add mode(values)                     | feature  | done-first-pass | 0 | f4ec3ee |
| 8 | add truncate(text, n)                | feature  | done-first-pass | 0 | 1b42d56 |
| 9 | multiply uses * operator             | refactor | done-first-pass | 0 | 40dca44 |
| 10| rename _c in median (no-op)          | refactor | done-first-pass | 0 | 68b468b |
| 11| extract _require_numbers helper      | refactor | done-first-pass | 0 | b6216ee |
| 12| negative-number tests add/subtract   | test     | done-first-pass | 0 | ad81506 |
| 13| test divide zero denominator (no-op) | test     | done-first-pass | 0 | 6180607 |
| 14| test mean empty list (no-op)         | test     | done-first-pass | 0 | d587e9d |
| 15| module docstring for textutils.py    | docs     | done-first-pass | 0 | de2adbc |
| 16| README Usage section                 | docs     | done-first-pass | 0 | c22ed15 |
| 17| __all__ in calckit/__init__.py       | docs     | done-first-pass | 0 | c6138e0 |
| 18| untested-functions research          | research | done-first-pass | 0 | (analysis only) |
```

### Run 2 (cloud, after tuning) — `harness-runs/run2-cloud-20260727-003558.md`

```
| # | task | kind | outcome | rework | time(s) | commit |
|---|------|------|---------|--------|---------|--------|
| 1 | divide returns None on b=0            | bug      | done-first-pass | 0 | 65 | 1023079 |
| 2 | mean([]) returns 0.0                  | bug      | done-first-pass | 0 | 78 | 0fd1d8a |
| 3 | slugify lowercases output            | bug      | done-first-pass | 0 | 60 | fe2628d |
| 4 | median averages two middle values    | bug      | done-first-pass | 0 | 69 | bdea2ee |
| 5 | add power(base, exp)                 | feature  | done-first-pass | 0 | 81 | 306f71a |
| 6 | add clamp(value, low, high)          | feature  | done-first-pass | 0 | 68 | 3fd5877 |
| 7 | add mode(values)                     | feature  | done-first-pass | 0 | 78 | c85f479 |
| 8 | add truncate(text, n)                | feature  | done-first-pass | 0 | 64 | a96073a |
| 9 | multiply uses * operator             | refactor | done-first-pass | 0 | 80 | 33d228a |
| 10| rename _c in median (no-op)          | refactor | done-first-pass | 0 | 48 | c7d0528 |
| 11| extract _require_numbers helper      | refactor | done-first-pass | 0 | 107| ff6b122 |
| 12| negative-number tests add/subtract   | test     | done-first-pass | 0 | 67 | b1670f8 |
| 13| test divide zero denominator (no-op) | test     | done-first-pass | 0 | 22 | 7dc49f4 |
| 14| test mean empty list (no-op)         | test     | done-first-pass | 0 | 22 | 1b523e5 |
| 15| module docstring for textutils.py    | docs     | done-first-pass | 0 | 72 | 2bb0b6f |
| 16| README Usage section                 | docs     | done-first-pass | 0 | 22 | ed93ccb |
| 17| __all__ in calckit/__init__.py       | docs     | done-first-pass | 0 | 94 | 9dd4ebd |
| 18| untested-functions research          | research | done-first-pass | 0 | 31 | ac1b4d5 |
```

### Run 3 (local) — `harness-runs/run3-local-qwen7b-20260727-013305.md`

`qwen2.5:7b` via jarvis `task loop`. Streak 1/18, completed 5/18 (tasks 1, 6, 11,
15, 18), first-pass 22%, ~23m total, $0. "done" here is LLM-judged, not pytest.

```
| # | task                          | kind     | outcome | stage         | time | reqs |
|---|-------------------------------|----------|---------|---------------|------|------|
| 1 | divide returns None on b=0    | bug      | done    | done          | 107s | 28   |
| 2 | mean([]) returns 0.0          | bug      | stuck   | clarification | 31s  | 8    |
| 3 | slugify lowercases            | bug      | stuck   | execution     | 23s  | 12   |
| 4 | median even-length avg        | bug      | stuck   | execution     | 269s | 44   |
| 5 | add power(base, exp)          | feature  | stuck   | execution     | 32s  | 11   |
| 6 | add clamp(value, low, high)   | feature  | done    | done          | 30s  | 12   |
| 7 | add mode(values)              | feature  | stuck   | execution     | 32s  | 12   |
| 8 | add truncate(text, n)         | feature  | stuck   | execution     | 65s  | 16   |
| 9 | multiply uses * operator      | refactor | stuck   | execution     | 33s  | 14   |
| 10| rename _c in median           | refactor | stuck   | clarification | 17s  | 7    |
| 11| extract _require_numbers      | refactor | done    | done          | 203s | 38   |
| 12| tests for add/subtract        | test     | stuck   | execution     | 56s  | 14   |
| 13| test divide zero denom        | test     | stuck   | execution     | 71s  | 17   |
| 14| test mean empty list          | test     | stuck   | clarification | 41s  | 10   |
| 15| textutils module docstring    | docs     | done    | done          | 47s  | 16   |
| 16| README Usage section          | docs     | stuck   | execution     | 119s | 29   |
| 17| __all__ in __init__.py        | docs     | stuck   | clarification | 18s  | 7    |
| 18| untested-functions research   | research | done    | done          | 195s | 33   |
```
