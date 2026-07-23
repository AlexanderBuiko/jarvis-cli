# Agent-driven Level-2 smoke — report

This is the task's literal Level 2: a **prose scenario**, read by an **LLM agent**
(Claude), which drives an **MCP** (the Browser MCP) to operate the real web UI and
records the result. Unlike the deterministic `WebAdapter` (Python + Playwright
running exact command strings), here nothing is hard-coded — the agent interpreted
the prose and decided each click.

- **Scenarios (prose):** `jarvis/smoke/scenarios/agent/*.md`
- **Target:** `python -m jarvis.web` (the real page)
- **Driver:** Claude, via the Browser MCP, clicking the **actual form buttons**
  (Create / List / Delete / Set), not the command box.

## How this differs from the WebAdapter

| | `WebAdapter` (automated) | This run (agent-driven) |
|---|---|---|
| Input | exact command strings | a prose scenario |
| Who decides the steps | the code | the LLM, from the prose |
| Drives | a generic command box | the real form buttons |
| Deterministic | yes (CI gate) | no (LLM in the loop) |

They are complementary: the WebAdapter gates every PR deterministically; this run
proves an agent can operate the UI from a plain description, and it exercises the
specific buttons the adapter does not.

## Results — 3/3 passed

### 1. Task lifecycle: create → verify → delete → verify — PASS
| Step | Action (agent, on the page) | Result |
|---|---|---|
| 1 | open the UI | page loaded |
| 2 | type `agent-demo` in Name, click **Create task** | `Task created: 'agent-demo' (34ccd486)` ✓ |
| 3 | click **List tasks** | list shows `agent-demo  34ccd486` ✓ (screenshot) |
| 4 | type `34ccd486` in Id, click **Delete task** | `Task 'agent-demo' deleted.` ✓ |
| 5 | click **List tasks** | `No saved tasks.` — gone ✓ |

The classic "create entity → check it appeared → delete → check it's gone", driven
entirely by the agent clicking real buttons.

### 2. Configuration round-trip — PASS
| Step | Action | Result |
|---|---|---|
| 1–2 | set Key `temperature`, Value `0.5`, click **Set** | `Updated: temperature = 0.5` ✓ |
| 3 | click **Show config** | `Active configuration: … temperature = 0.5` ✓ |

### 3. Bad input rejected in the UI — PASS
| Step | Action | Result |
|---|---|---|
| 1 | set Key `max_tokens`, Value `-100`, click **Set** | `Error: max_tokens must be a positive integer` ✓ |

## What broke

Nothing. All three prose scenarios passed on the first drive-through.

## Screenshots

Captured live in the session transcript (the task-list-after-create view is the
key one). Reproduce by running `python -m jarvis.web` and following the prose in
`jarvis/smoke/scenarios/agent/`.

## Honest limit

This is agent-driven, so it needs Claude in the loop — it is **not** headless-CI
automatable. That is inherent to "an LLM interprets the scenario": the LLM is the
driver. For a self-contained autonomous version, jarvis could register a Playwright
MCP server (`npx @playwright/mcp`) and let its own agent drive it from the prose —
buildable on jarvis's existing MCP client + agent tool loop, but non-deterministic
and it costs LLM calls, so it complements rather than replaces the deterministic
CI gate.
