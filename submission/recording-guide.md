# Recording guide — Day 3 (two levels of testing)

The point of the video: show that **the agent triggers both levels itself**.
You screen-record while the agent finds modules and writes tests (Level 1), then
drives the UI through an MCP (Level 2). You mostly paste two prompts and watch.

All commands use `.venv/bin/python3` (no bare `python`).

---

## Before you press record

1. Open a terminal, go to the repo, be on the branch:
   ```bash
   cd /Users/alexanderbuyko/PycharmProjects/jarvis-cli
   git checkout two-level-testing
   ```
2. Open a **fresh** Claude Code session in this repo (no prior context).
3. Have the screen recorder ready (macOS: `Cmd + Shift + 5`).

---

## Press record. Then do the parts in order.

### Part A — Level 1: the agent finds modules, writes tests, runs them

Paste this prompt to the agent:

> Level 1 — code autotests. Find at least 3 Python modules under `jarvis/` that
> have no dedicated test file and contain real logic with no network dependency.
> Write unit tests for them following this project's conventions
> (`unittest.TestCase` with `tempfile.TemporaryDirectory` for isolation, no mocking
> `os`, no network). Then run them with `.venv/bin/python3 -m pytest -q` on just
> those new files and confirm they pass on the first run. Report which modules you
> covered and the pass count.

What the camera should catch:
- the agent naming the uncovered modules it picked,
- the new `tests/test_*.py` files it writes (3+),
- the `pytest` run showing they pass first time.

### Part B — Level 2: the agent drives the UI through an MCP

First, in your terminal, start the web UI (leave it running):
```bash
.venv/bin/python3 -m jarvis.web --port 8766
```
You should see: `Jarvis web UI on http://127.0.0.1:8766`.

Then paste this prompt to the agent:

> Level 2 — UI smoke through the browser MCP. The web UI is running at
> http://127.0.0.1:8766/. Read the three user scenarios in
> `jarvis/smoke/scenarios/agent/*.md`. For each scenario, open the page in the
> browser (use the Browser MCP / Playwright MCP), and perform the steps by
> **clicking the real buttons and filling the forms** — do not use the command
> box. Take a **screenshot at each step**. After each scenario, record whether it
> passed or failed, and if something broke, say where. Produce a short report at
> the end.

What the camera should catch:
- the agent opening the page,
- it filling fields and clicking Create / List / Delete / Set,
- a screenshot after each step,
- the pass/fail summary and the "what broke" note.

The three scenarios it reads:
- `01_task_lifecycle.md` — create a task → see it in the list → delete → confirm gone
- `02_config_roundtrip.md` — set a config value → show config
- `03_config_validation.md` — set a bad value → the UI rejects it

### Part C (optional) — one combined report, both levels

Back in the terminal:
```bash
.venv/bin/python3 scripts/qa_report.py --report submission/qa-report.txt
```
Shows Level 1 + Level 2 (cli) + Level 2 (web) in one report with a PASS/FAIL line.

---

## Stop recording. Save.

- Save the video as `submission/day3-recording.mov` (or wherever you keep them).
- Stop the web server in its terminal with `Ctrl + C`.

---

## Notes

- The Level-1 tests the agent writes on camera are **new** (the modules I tested
  earlier — profile store, behaviour log, invariant store — are already covered,
  so the agent must find different uncovered ones). Keep them or discard after the
  recording; they are a live demonstration, not the committed deliverable.
- If the browser MCP is not available in your session, the agent cannot drive the
  page. In that case start the recording over with the MCP enabled, or drive the
  page yourself while narrating — but the intended demo is the agent doing it.
- Everything already committed on `two-level-testing` is the standing evidence;
  the video shows the agent producing it live.
