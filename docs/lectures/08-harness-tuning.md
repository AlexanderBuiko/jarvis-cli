# Week 8 — Tuning a Code Assistant into a Personal Harness

**Source:** `transcriptions/8неделя1поток-саммари.md`,
`8неделя1поток-расшифровка.md` (+ alt raw `08-harness-raw-alt.txt`)
**Theme:** Tune a code assistant (Claude Code, Cursor) from a prompt tool into a
full **execution loop** — you are the operator, the agent plans, routes to
sub-agents, uses skills and commands, following your rules and style.

## Code-assistant architecture

- **Main agent** — the centre; interprets your commands and runs the system. Its
  job is to **plan and route**, not to do the work itself.
- **Sub-agents** — specialised, isolated processes with their own context and
  system prompt. Claude Code caps concurrent sub-agents at **5**.
- **Skills** — narrow abilities the agent calls by context (e.g. `PR Summary`).
- **Commands** — shortcuts to drive the agent (e.g. a `Spec Interview` command
  that generates a plan).
- **MCP and RAG** — external tools and knowledge bases.

## Rules

- **Global rules** — your general working style; set them, always.
- **Project rules** — override globals per project (different stack, design
  system). Works by **inheritance**.
- **Profile** — how you want to interact (style, may it argue, language). Saves
  tokens (e.g. ask for terse answers).
- **Invariants** — clear can/can't rules (e.g. "always Kotlin").
- **Task state** — write an explicit flow (research → plan → execute → validation)
  and the transition rules, to avoid chaos.

## Organising sub-agents

- **Parallel** — saves time when tasks are independent (fix 5 different bugs).
- **Sequential** — clean result when the next agent depends on the previous.
- **Conditional routing** — e.g. reviewer finds a defect → back to the coder.
- Every sub-agent needs clear **input/output contracts** — big token savings,
  fewer hallucinations.

## Practical advice

- **Do not work in the main agent.** Use it only to plan and hand out tasks, so
  its ~160–180k-token window does not fill up.
- **Set up a global profile** with your style, invariants, and explicit stages —
  it is the base of the whole execution loop.
- **Use hooks** — notifications (e.g. Telegram) or sounds so you know when a
  background agent finishes.
- **Gentleman's set of MCP:** local models, web clicker (Playwright/Lightpanda),
  mobile clicker, task tracker (GitHub, Jira), Figma, GitHub, and token-saving
  tools (e.g. AST index).
- **Spend an hour on setup** — it saves dozens of hours of later debugging.

> "The more often you correct your model, the worse your execution loop is tuned."

## Maps to jarvis-cli (and this repo's `.claude/` config)

- This is the meta-week: it shapes the harness that builds jarvis, not jarvis
  itself. See `week8-harness-tuning` memory.
- Global rules → `~/.claude/CLAUDE.md`; project rules → this repo's `CLAUDE.md`
  (inheritance: "extend and specialise, never contradict").
- Profiles (selector → profile → sub-agents) → `~/.claude/profiles/`.
- Sub-agents mirror the app's pipeline roles → `.claude/agents/`
  (planner/executor/validator/reviewer/consolidator).
- Skills → `.claude/skills/` (add-repl-command, add-mcp-server, update-smoke).
- Two-level testing + smoke + web UI landed this week.

## Week's assignment

Tune your code assistant into a personal "Jarvis": set global + project rules, a
profile, invariants, and an explicit task state machine; wire sub-agents with
contracts and the right parallel/sequential/router topology; add skills, commands,
hooks, and the MCP set. The deliverable is a tuned execution loop, not a feature.

> Related deliverable in this repo: `deliverables/08-local-optimization.md`
> (optimising a local model for a specific task — a separate day's assignment).
