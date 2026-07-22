# Level-2 web smoke — report

The agent drove the **real web UI** (`python -m jarvis.web`) through the Browser
MCP: opened the page, filled forms, clicked buttons, and checked the result on the
page — the literal Level-2 loop that the terminal-only app could not offer before.

- **Target:** `http://127.0.0.1:8765/` served by `jarvis/web/` (stdlib http.server
  over the same `_dispatch` the CLI runs).
- **Driver:** Browser MCP (in-app browser), agent-operated.
- **Scenarios:** `jarvis/smoke/scenarios/web/*.json`.

## Results — 3/3 passed

### 1. Config round-trip — PASS
| Step | Action (on the page) | Result on the page |
|---|---|---|
| 1 | fill Key=`temperature`, Value=`0.7`, click **Set** | `Updated: temperature = 0.7` ✓ |
| 2 | click **Show config** | `Active configuration: … temperature = 0.7` ✓ |

### 2. Task lifecycle: create → check → delete → check — PASS
| Step | Action | Result |
|---|---|---|
| 1 | fill Name=`web-smoke`, click **Create task** | `Task created: 'web-smoke' (d4199572)` ✓ |
| 2 | click **List tasks** | list contains `web-smoke  d4199572` ✓ |
| 3 | fill Id=`d4199572`, click **Delete task** | `Task 'web-smoke' deleted.` ✓ |
| 4 | click **List tasks** | `web-smoke` absent ✓ |

This is the classic "create entity → verify it appeared → delete → verify it's
gone" smoke, run entirely by clicking the real UI.

### 3. Config validation in the UI — PASS
| Step | Action | Result |
|---|---|---|
| 1 | fill Key=`max_tokens`, Value=`-100`, click **Set** | `Error: max_tokens must be a positive integer` ✓ |

The Day-3 config bug-fix now surfaces through a **web UI**, clicked by the agent —
the same behaviour guarded at three layers: the validator (fix), its unit test
(Level 1), the CLI smoke (Level 2 terminal), and now the web smoke (Level 2 web).

## What broke

Nothing. All three scenarios passed on the first drive-through.

## Screenshots

Captured live during the run (in the session transcript): the config round-trip
result, the task list, and the validation error each rendered on the page. Re-run
`python -m jarvis.web` and repeat the steps above to reproduce.

## How this fits the framework

The run above was **agent-driven via the Browser MCP** (a human/agent clicking the
real form buttons). It is now also **automated**: `jarvis/smoke/web.py`
(`WebAdapter`) drives the page in headless Chromium via Playwright, so
`python -m jarvis.smoke --platform web` runs the same scenarios with no human, and
`scripts/qa_report.py` includes a web tier that runs in CI (skipped when the
optional `web` extra is absent, so the fast CLI gate never needs a browser).

Two coverage angles, both real: the MCP run exercised the specific form buttons
(Set / Create / Delete); the automated adapter drives a generic command box, so it
covers the browser + JS + backend + render path deterministically. The command box
is what lets one command-string scenario run on both the `cli` and `web` adapters.
