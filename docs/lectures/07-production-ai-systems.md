# Week 7 — Production-Ready AI Systems

**Source:** `transcriptions/07_7_week_english_copy.txt`,
`07_7_week_summary_english_copy.txt` (DOCX-in-`.txt`; extract with a zip reader)
**Theme:** The final, most practical week — assemble everything into one working
system: sub-agents, system tools, pipelines with monitoring and error handling.

## LLM agent as a mini-OS

A modern AI agent (Claude Code, Cursor, OpenCode) is a **mini operating system**:
it has access to tools (files, MCP, bash) and manages resources to finish a task.
Goal metric: solve the user's task in the **fewest iterations** — ideally one
instruction, no session breaks. Sessions break when context runs out; the fix is
sub-agents.

## Sub-agents and delegation

A **sub-agent** solves one concrete subtask in its own full context window, so
the orchestrator's window does not overflow. Use one agent for simple linear
tasks; use sub-agents for complex, non-deterministic tasks (research → plan →
execute → validate). Delegation patterns:

- **Fan-out** — orchestrator runs independent sub-agents in **parallel** (e.g.
  refactor backend and mobile at once). Cuts wall-clock time 2–10×.
- **Chain** — sequential; one agent's output is the next one's input.
- **Router** — pick which sub-agent to run based on a condition/request type.

Give every sub-agent clear **input/output contracts** — saves tokens and reduces
hallucination.

## System tooling

Tools to interact with the environment: read/write files, run bash, launch apps,
plus MCP and RAG. Architecture: **Tool Registry** (all tools registered) +
**Tool Executor** (on the LLM's request, find and run the tool, return the
result). **Dangerous operations** (delete files, `git push`) require explicit
user confirmation — Human-in-the-Loop.

## AI pipelines

An automated process started by a **trigger** (PR, schedule, event) that runs an
AI agent on the input to produce a result. Canonical example: **automatic code
review on a Pull Request**.

Error handling and fallback are mandatory:

- **Retry** — repeat with a different prompt/model.
- **Fallback** — an alternative strategy, or notify a human.
- **Timeouts.**
- Never a fully automatic process — always keep a human in the loop.

## Metrics

- **Latency** — percentiles (P50, P95, P99).
- **Cost** — tokens per operation (e.g. per PR).
- **Quality** — human rating of usefulness (e.g. 1–10).
- **Success rate** — share of runs needing no human intervention.

Measure a baseline; test the pipeline on historical/reference data; compare
prompt and model versions by metrics.

## Maps to jarvis-cli

- Sub-agent patterns → `jarvis/pipeline/swarm.py` (reviewer panel, fan-out) and
  `parallel.py` (topological waves). See `project_validation_swarm` and
  `project_parallel_execution` memories.
- System tools → `jarvis/mcp_servers/` (files, git) + permission gate.
- PR-review pipeline → `jarvis/review/` (`python -m jarvis.review`, the CI entry
  point in `ai-review.yml`).
- The whole week is the seed of the Week-7 dev assistant
  (`project_week7_dev_assistant` memory).

## Week's assignment

Relax and build something real: design your mini-OS (one-session UX), add
sub-agents for a complex task using fan-out/chain/router, build a Tool Registry +
Executor with dangerous-op confirmation, build one AI pipeline (start with PR
code review), add retry/fallback/human-in-the-loop, and add metrics + testing.
Ship a prototype that solves a real task, not a demo.
