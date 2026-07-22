# Day 2 — Agent-mode profiles

Three task profiles for the assistant. A profile is **not** a subagent — it is a
workflow that the global `CLAUDE.md` selects and that orchestrates the Day-1
subagents.

```
~/.claude/CLAUDE.md            SELECTOR — reads the request, picks a profile
        │
        ├─ profiles/bug-fix.md          workflows: which subagents,
        ├─ profiles/research.md          in what order, for what purpose
        └─ profiles/convention-audit.md
                    │
                    ▼
.claude/agents/  planner · executor · validator · reviewer · consolidator
                    THE WORKERS the profile orchestrates
```

| Profile | Global file | Chain (subagents) | Writes? |
|---|---|---|---|
| Bug Fix | `~/.claude/profiles/bug-fix.md` | reproduce → `planner` → `executor` → `validator` | yes |
| Research | `~/.claude/profiles/research.md` | `planner` (read-only) → answer | no |
| Convention Audit | `~/.claude/profiles/convention-audit.md` | `reviewer` ×N → `consolidator` | no |

Snapshots of the global files live in this repo as evidence:
[`global-CLAUDE.selector.md`](global-CLAUDE.selector.md) and
[`profiles/`](profiles/).

## The design choice

The teacher's "what the assistant SHOULD NOT do" is enforced by the **chain, not
prose**. The research and audit profiles simply never invoke `executor` — the only
subagent that can write — so "do not change the code" is a structural fact, not a
rule the model must remember. This is the same reasoning that keeps the Day-1
`validator` read-only.

Bug Fix keeps its "do not ignore the tests" constraint in its response format,
because it *must* write: every row of "What I checked" must be a command that was
actually run, and anything unrun goes to "Not done".

### Why not subagents (the first attempt)

The profiles were first built as three extra subagents in `.claude/agents/`. That
was the wrong form: a subagent is a *worker* the main agent delegates to, while a
profile is a *mode the main agent itself enters* that decides which workers to
use. The task asks for the second. Corrected per the tutor's guidance — profiles
in a global folder, the global `CLAUDE.md` reduced to a selector — and recorded in
[`iterations.md`](iterations.md).

## Each profile answers the four required questions

Read the agent file for the full text. In brief:

- **System prompt / instructions** — the body of each `.md`.
- **Should do** — the "What you must do" section.
- **Should not do** — the "What you must NOT do" section.
- **Response format** — the fenced template at the end. Bug Fix: found / fixed /
  checked. Research: answer / evidence / files. Audit: findings / stale rules /
  verdict.

## Testing protocol

Each profile is tested on **one real task, one run, working result required** —
the same standard as Day 1. Evidence goes in the per-profile directories.

| Profile | Task | Verified ground truth |
|---|---|---|
| Bug Fix | `bugfix-task.md` | 9 config params in `_PARAM_PARSERS` have no `_PARAM_VALIDATORS` entry, so `config set max_tokens -100` is accepted while `config set temperature 999` is refused. |
| Research | `research-task.md` | 6 of 13 REPL commands have no test: `invariants`, `mcp`, `personalize`, `profile`, `quiz`, `session`. |
| Convention Audit | `audit-task.md` | audit the working diff; findings are checkable by hand against `CLAUDE.md`. |

The ground truth was confirmed by running the checks directly (see each task file)
**before** any profile ran, so the profile's answer can be scored exactly.

### Running one

Open a fresh session and give the task file's prompt verbatim. The global
selector should pick the profile on its own — that routing is part of what is
being tested, so do not name the profile yourself. Capture the transcript to
`<profile>/transcript.md`, then record the outcome in `<profile>/result.md`
against the task's success criteria. Note in the transcript whether the selector
chose the right profile unprompted.

For Bug Fix, reset the tree afterwards — the fix is evidence, not something to
keep unless you want it:

```bash
git checkout -- . && git clean -fd jarvis/ tests/
```

## What had to change after the first attempt

Recorded in [`iterations.md`](iterations.md) as each profile is exercised — the
teacher asks specifically for "what had to be finalised after the first attempt".
