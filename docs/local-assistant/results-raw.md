# Day 4 — raw capture sheet

Fill one block per assistant as you run. These numbers feed straight into
[comparison.md](comparison.md). Scoring rules: [run-guide.md](run-guide.md) Phase 4.

Legend: house-style checks `1234567` → mark each ✓/✗. TaskA completion = yes/partial/no.
TaskB points = /4 (parser, validator+comment, help row, test).

---

## Cloud — Claude Code   *(run 2026-07-26; reference diff: submission/day4/cloud-baseline.diff)*

**Task A (feature gen — `models` command)**
- house-style: 1✓ 2✓ 3✓ 4(n/a — added to existing module) 5✓ 6✓ 7✓  → 6/6 applicable
- completion: **yes** — handler *returns* a string; wired all 5 registration points
  (handler, loop import, dispatch branch, HELP_TEXT, COMMAND_TREE)
- first try: **yes** · turns to fix: 0 · time: fast, network-bound (see note)

**Task B (agent mode — `presence_penalty`)**
- registration points found: **4/4** (parser, validator + `#` comment, help-table row, test)
- house-style: all applicable ✓ (antipattern-5 satisfied: validator ships with the parser)
- first try: **yes** · turns to fix: 0 · time: fast, network-bound
- notes: found every point unaided; matched the existing `_active_provider_model`
  resolution (incl. the ollama cloud-id guard) without being pointed at it. Full
  suite 469/469 green, ruff clean on first run.

**Timing note:** cloud time isn't stopwatch-comparable to local token-rate — it's
network round-trips, not tokens/sec on your GPU. Recorded as "fast, network-bound";
judge local speed on its own felt latency, not against this number.

---

## Local — Qwen2.5-Coder 7B   *(run 2026-07-26, Continue agent mode)*

**Task A** — house-style **0/7** · completion **no** · first try **no** · turns abandoned · time n/a
- Ignored the project entirely: invented `REPLCommand`/`UnitTest` classes with
  hard-coded `model1`/`model2` fake data, targeted a non-existent `main.py`, left
  `# ... existing code ...` placeholders (proof it never read the real files).
- Returned a `list[dict]`, not a string (breaks the handler convention); no
  relative imports, no typing, no real `unittest.TestCase`, no registration.

**Task B** — points **0/4** · house-style n/a · first try **no** · turns 0 · time n/a
- Produced a plan referencing a hallucinated `register_config_parameter` function
  (does not exist). Emitted a `grep_search` tool call as JSON text in the chat —
  it **never executed**. Zero edits applied.

**Root cause:** the 7B couldn't drive the agent tool-loop (read → grep → edit). It
guessed at the codebase instead of reading it, so both answers are hallucinations.
This is the "cloud indispensable for multi-file/agent work" evidence.

**Reproduced (2nd agent-mode attempt, same day):** identical failure. Task A →
hallucinated a `repl.py` with `model1`/`model2` and a `print`-based method (the
test even mocks `sys.stdout` — doubly against the return-a-string convention).
Task B → same hallucinated `registerConfigParameter`, grep never fired, 0 edits.
Marginally better only in reaching for `unittest.TestCase`; still 0/7 project-valid.

**3rd attempt — Task A in CHAT mode, active file attached:** still 0/7. Invented
`REPLCommand` + `model1`/`model2`, `print`-based, targeted `main.py`, referenced a
non-existent `captured_output()`. Zero real project symbols in any of the three
runs — the tell that the model never grounded in the code (context not reaching it,
or 7B too weak to use it).

**Verdict for 7B:** fails Task A and Task B on this project. Diagnostic not yet run
(the "list functions in the attached file" grounding check) to split "broken
context pipe" from "weak model" — noted in [report.md](report.md) as the next step
if the setup is revisited.

---

## Local — DeepSeek-Coder-V2 16B-lite

**Not run this session.** Skipped because `ollama show` reports **no `tools`
capability** → it cannot do agent mode (Task B) at all; only Chat would have been
possible. 7B + 14B already gave two measured local chat data points, both failing,
so a third chat-only model was not worth the pull under deadline.

---

## Local — Qwen2.5-Coder 14B   *(run 2026-07-26)*

**Task A (Chat mode)** — house-style **0/7** · completion **no** · first try **no**
- **Identical failure to the 7B** — bigger model did not help chat feature-gen.
  Created `main.py` (wrong), `list_models()` with `print`, `get_configured_models()`
  /`get_default_model()` (invented), OpenAI/Hugging Face fake data, `# ... existing
  code ...` placeholders. Test mocks `src.main` (non-existent) and captures stdout.
- Ignored the attached real files. No project grounding.

**Task B (Agent mode)** — points **0/4** · first try **no** · turns abandoned
- **Better *process* than 7B:** native tools fired — it ran a codebase search and
  surfaced two **real** files (`jarvis/repl/commands.py`, `jarvis/repl/loop.py`).
  That's real project grounding the 7B never reached.
- **Still wrong *outcome*:** invented a `validate_config(config)` function that does
  not exist here, added it to `commands.py` **and** `loop.py` (neither is where
  config params are registered — that's `jarvis/config/manager.py`), used an ad-hoc
  `isinstance` dict check instead of the `_PARAM_PARSERS`/`_PARAM_VALIDATORS`
  pattern, and created `test_commands.py`/`test_loop.py` for the invented function.
- Net: found real file *names* via search, but missed the real mechanism and edited
  the wrong places. 0/4 registration points correct.

notes: size helped agent *file discovery*, not code correctness. Neither local
model produced applyable, in-style code for either task.

---

## Autocomplete — Qwen2.5-Coder 1.5B-base (local only)   *(run 2026-07-26 — WORKS)*

- latency feel: **instant** — usable at keystroke speed.
- single-file-context test **passed**: completed the in-file symbols
  (`WARP_COIL_CALIBRATION_HZ`, `dilithium_purity_pct`, `high`), not generic guesses.
- usefulness: good for line/block completion within the current file. Recorded on
  video. This is the one local feature that clearly works well.

---

## RAM / speed observations (optional but good evidence)

- `ollama ps` output while each model was loaded (size in RAM):
- did the 14B cause pressure / swap? which models could co-run with autocomplete?
