# Day 2 — Agent-mode profiles

Three task profiles for the assistant, each a subagent in
[`.claude/agents/`](../../.claude/agents/), each scoped by the tools it is granted
rather than by instructions alone.

| Profile | File | Tools | Constraint made structural |
|---|---|---|---|
| Bug Fix | `bug-fix.md` | read + write + bash | must show test output to claim "checked" |
| Research | `research.md` | read-only | cannot modify code — no edit tools exist |
| Convention Audit | `convention-audit.md` | read-only | cannot fix what it reports on |

## The design choice

The teacher's "what the assistant SHOULD NOT do" is enforced through **tool
grants, not prose**. `research` and `convention-audit` are given no `Edit` or
`Write` tool, so "do not change the code" is not a rule the model must remember —
it is a capability the model does not have. This is the same reasoning that keeps
the Day 1 `validator` read-only: a role that reports must not be able to alter
what it reports on.

Bug Fix keeps its constraint (do not ignore the tests) in prose, because it *must*
write. It is bound instead by its response format: every row of "What I checked"
must be a command that was actually run, and anything unrun goes to "Not done".

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

Open a fresh session, invoke the subagent by name with the task file's prompt,
and capture the transcript to `<profile>/transcript.md`. Then record the outcome
in `<profile>/result.md` against the task's success criteria.

For Bug Fix, reset the tree afterwards — the fix is evidence, not something to
keep unless you want it:

```bash
git checkout -- . && git clean -fd jarvis/ tests/
```

## What had to change after the first attempt

Recorded in [`iterations.md`](iterations.md) as each profile is exercised — the
teacher asks specifically for "what had to be finalised after the first attempt".
