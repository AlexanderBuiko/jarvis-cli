# Profile: Bug Fix

A workflow for "something is broken and must end up working". This file is the
**chain**: it says which subagents run, in what order, and why. It is not a
subagent itself.

Selected when the request asserts a symptom (an error, a wrong output, a crash,
a regression) and expects a working result — not just an explanation.

## The chain

| Step | Subagent | Purpose |
|---|---|---|
| 1. Reproduce | *(main agent)* | Run the failing case and see it fail before anything is touched. A bug you cannot reproduce, you cannot fix. |
| 2. Diagnose | `planner` | Trace from the symptom to the root cause. Name the cause in one sentence, with `path:line`, before any edit. |
| 3. Fix | `executor` | The smallest change that removes the cause — not the symptom. Ship a test that fails without the fix and passes with it. |
| 4. Verify | `validator` | Run the full test suite and the linter, read the output, confirm nothing else broke. Read-only by design, so it cannot hide a failure by patching over it. |

`executor` is the only writing subagent in this chain. If the diagnosis shows the
plan was wrong rather than the code, loop back to `planner` before fixing again.

## Must do

- Reproduce first, fix second.
- State the root cause before editing.
- Add a regression test in the same change.
- Run the suite and linter and show the real output.

## Must not do

- Do not skip the tests. A fix reported without a green suite is a guess.
- Do not patch the symptom and leave the cause.
- Do not expand scope. Fix this bug; note others, don't fix them.
- Do not claim a check ran unless it ran and the output was read.

## Response format

```
## What I found
<root cause, with path:line>

## Reproduction
<exact command and the failing output, before the fix>

## What I fixed
<the change, path:line, why it addresses the cause not the symptom>

## What I checked
| Check | Command | Result |
|---|---|---|

## Not done
<deferred or out of scope, or "nothing">
```

Every "What I checked" row is a command that was run and output that was read.
Anything unrun goes to "Not done" with the reason.

Project-specific commands (test runner, linter, repro harness) are supplied by the
project's own `CLAUDE.md`. This profile stays stack-agnostic.
