---
name: update-smoke
description: After adding or changing a feature, refresh the Level-2 smoke scenarios and rerun the whole QA gate (code tests + UI smoke). Use when a new command, flag, or behaviour lands and the smoke coverage should catch up.
---

# Updating smoke after a feature lands

The trigger is: "I added a feature — update the smoke scripts and run it all
again." The goal is that the smoke suite keeps matching the real interface, and
that both test levels still pass.

## 1. Decide what the feature added to the interface

Smoke drives the **real terminal**, so only a change a user can *type* needs a
scenario:

- A new command or sub-command (`notes add`, `config set <newkey>`) → add a
  scenario that drives it and checks its output.
- A new validation or error path → add a step asserting the rejection message
  (see `02_config_validation.json` — it smokes a bug-fix through the UI).
- A pure library change with no new user-facing command → usually **no** new
  scenario; a Level-1 unit test covers it instead. Do not invent a smoke path
  for something the terminal cannot reach.

## 2. Add or edit a scenario

Scenarios are JSON under `jarvis/smoke/scenarios/`, run in sorted order:

```json
{
  "name": "what a user should be able to do, in one line",
  "platform": "cli",
  "steps": [
    {"action": "config set temperature 0.7", "expect": "temperature = 0.7"},
    {"action": "config show",                "expect": "temperature"}
  ]
}
```

Rules that keep it deterministic (this is why the suite passes every run):

- **Command mode only.** `config`, `task`, `thread`, `help`, … never call the
  LLM, so no network and repeatable. Do **not** add chat-mode prompts — they hit
  the model and belong to a live, opt-in tier, not this gate.
- `expect` is a substring the step's captured output must contain. Pick a stable
  fragment of a real reply — confirm it first by running the command in a normal
  `jarvis` session, or check the handler's return string in
  `jarvis/repl/commands.py`.
- `expect` is optional; omit it to just record a capture (a "screenshot") without
  asserting.
- Each scenario runs in its own throwaway `HOME`, so it never sees the real
  `~/.jarvis` and never leaks state to the next scenario. Do not assume prior
  state.

## 3. Rerun the whole QA gate

Both levels, one report:

```bash
python scripts/qa_report.py            # Level-1 pytest + Level-2 smoke → one report
```

Or each level alone while iterating:

```bash
.venv/bin/python -m pytest -q          # Level 1
.venv/bin/python -m jarvis.smoke       # Level 2 (add --report smoke.txt to save it)
```

## 4. If a smoke step fails

The report prints each step's captured terminal output verbatim — that block is
the evidence. A failure means the `expect` string was not in the capture. Either
the interface changed (update the `expect`) or the feature is broken (the capture
shows what it returned instead). Fix the cause, not the assertion, unless the
assertion is genuinely stale.

New behaviour ships with coverage: a new user-facing path gets a smoke scenario,
a new library path gets a Level-1 test, in the same change.
