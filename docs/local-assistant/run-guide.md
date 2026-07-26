# Day 4 — run guide (get the runs, frame the result)

This is the master runbook. It gives you two fixed tasks, the exact per-model
loop, how to score each run, and how the scores become the comparison table.
Prompts live **here only** — [setup.md](setup.md) points back to this file so
they can't drift.

You run each task against **every chat model** you pulled and against the
**cloud** assistant (Claude Code — me). Same prompt, same tree, every time.

- **Assistants to cover:** cloud (Claude Code) · Qwen2.5-Coder 7B · DeepSeek-V2
  16B-lite · Qwen2.5-Coder 14B.
- **Where things go:** screenshots → `submission/day4/`, raw scores →
  [results-raw.md](results-raw.md), final table → [comparison.md](comparison.md).

---

## Phase 0 — prep (once)

```bash
git checkout day4-local-boost
mkdir -p submission/day4
git status         # must be clean before each run so every model starts equal
```

Two rules that keep the comparison fair:
1. **Reset the tree between runs.** A model may write files (agent mode). Before
   the next model, undo *only the code dirs it can touch* — this leaves your
   untracked `docs/local-assistant/` and `submission/day4/` safe:
   ```bash
   git checkout -- jarvis tests && git clean -fd jarvis tests
   ```
   (Do **not** run a bare `git clean -fd` — it would delete the uncommitted
   Day-4 docs and your screenshots.)
2. **Time it the same way every time.** For local, read Ollama's own numbers:
   after a chat reply, run in a terminal
   `ollama ps` (shows the loaded model) and note the **eval rate** Continue logs,
   or just stopwatch **time-to-first-token** and **time-to-done**. For cloud,
   stopwatch the same two. Approximate is fine — record the method, be consistent.

---

## Phase 1 — autocomplete check (2 min, local only)

Cloud has no tab-autocomplete equivalent, so this is a local-only row.

1. Open `jarvis/config/manager.py`. Put the cursor on a new line inside a function.
2. Type a comment like `# return the parser for a given key` and press Enter.
3. Watch for grey ghost text. Accept a few (Tab), dismiss others (Esc).
4. Record in [results-raw.md](results-raw.md): latency feel (laggy / fine / instant),
   and whether completions were usable (accepted vs dismissed).

Screenshot one good completion → `submission/day4/autocomplete.png`.

---

## Phase 2 — Task A: feature generation (Day-1 style)

**What it tests:** raw code quality + house-style adherence in a single answer.
Use Continue **chat** mode (not agent).

Paste this exact prompt:

> Add a REPL command `models` for this project. It lists the configured LLM
> models, showing each model's provider and whether it is the active default.
> Follow the project's conventions exactly and include a unit test. Return the
> code only — no explanation.

Do it for each chat model (switch model in the Continue dropdown), and once
against me (cloud). Screenshot each answer → `submission/day4/taskA_<model>.png`.

Score each answer with the **house-style checklist** (Phase 4). You are grading
the *code*, not whether it's wired in — this is a generation-quality test.

---

## Phase 3 — Task B: agent mode (Day-2 style)

**What it tests:** project understanding + multi-file coherence — can it find the
places to change on its own? Switch the Continue panel to **Agent** mode.

Paste this exact prompt:

> Add a new config parameter `presence_penalty`: a float valid in the range
> -2.0 to 2.0. Register it in every place the existing config parameters are
> registered — find those places yourself — and add a test that a valid value is
> accepted and an out-of-range value is rejected. Show me the plan first, then
> make the edits.

The **ground truth** (what a correct answer touches — use it to score, don't
paste it to the model):
- `jarvis/config/manager.py` → `_PARAM_PARSERS` (add `"presence_penalty": float`)
- `jarvis/config/manager.py` → `_PARAM_VALIDATORS` (range check `-2.0..2.0` **with a `#` comment**)
- `jarvis/repl/commands.py` (~line 154) → the help-text table row
- a test in `tests/` (accept valid, reject out-of-range)

Verify a run actually works, in a terminal:
```bash
.venv/bin/python -m jarvis --version >/dev/null 2>&1   # sanity: imports
# after the model's edits:
grep -n presence_penalty jarvis/config/manager.py jarvis/repl/commands.py
.venv/bin/python -m pytest -q tests/ -k presence 2>&1 | tail -5
```

Do it for each chat model and once against cloud. Screenshot the plan + the diff
→ `submission/day4/taskB_<model>.png`. **Reset the tree (Phase 0 rule 1) before
the next model.**

---

## Phase 4 — scoring (turn each run into numbers)

Two scores per run, filled into [results-raw.md](results-raw.md).

**House-style checklist — 1 point each, score /7** (both tasks):

| # | Check | Pass if… |
|---|---|---|
| 1 | Relative imports | `from ..x import`, never `from jarvis.x import` |
| 2 | PEP 604/585 typing | `str \| None`, `list[dict]`; no `Optional`/`List` |
| 3 | Output channel | library code returns strings; no stray `print` |
| 4 | `from __future__ import annotations` | present at top of any new module |
| 5 | Test included | real test, `tempfile`, no network, sentence-style name |
| 6 | Naming | `…Client/…Store/…Agent/…Result`, `_private`, `JARVIS_*` |
| 7 | Docstring style | why-not-alternative prose; no `Args:`/`Returns:` |

**Task-completion — Task A:** did it produce a working command handler that
*returns* a string (the harder-to-guess convention)? yes / partial / no.
**Task-completion — Task B:** registration points found, **/4** (parser,
validator+comment, help row, test).

Plus per run: **first try worked?** (yes/no), **turns to correct** (count),
**wall-clock** (first-token / done).

---

## Phase 5 — frame the result

1. Move each run's numbers from [results-raw.md](results-raw.md) into the table
   in [comparison.md](comparison.md) (replace every `⟨fill⟩`).
2. Write the recommendation section — it must answer the three graded questions:
   - **For which tasks is local enough?** (point to your own scores: if a 7B
     nailed Task A house-style /7 and felt fast, say so.)
   - **Where is cloud indispensable?** (point to Task B: if locals missed
     registration points or lost multi-file coherence, that's your evidence.)
   - **Best local combo on this box:** which model + params + context size won.
     Name the winner and the number that decided it.
3. Keep the Day-1 note already in [comparison.md](comparison.md): only the
   code-style slice of the rules went into the local system prompt — that split
   is a finding, not an omission.

**Honesty rule (same as invariant #3):** every number is measured on your
hardware. If you didn't run a model, leave its column blank — don't infer it.

---

## Fast path (if time is short)

Minimum that still satisfies the task: **two** chat models (7B + one other) ×
**two** tasks, plus cloud, plus the autocomplete row. That fills the table with a
real 3-way comparison and a defensible recommendation. Add the third model only
if the first two disagree and you want a tie-breaker.
