# Profile: Convention Audit

A workflow for "does this code follow our conventions?". This file is the
**chain**: it says which subagents run and why. It is not a subagent itself.

Selected when the request asks whether code matches the project's written rules —
"audit X against our conventions", "review this before I commit", "does this
follow our style". The yardstick is `CLAUDE.md`, not correctness or design.

## The chain

| Step | Subagent | Purpose |
|---|---|---|
| 1. Review | one or more `reviewer` | Each checks the target against `CLAUDE.md` from its own angle (layering, typing, naming, error handling), independently. Run in parallel; they never see each other. |
| 2. Consolidate | `consolidator` | Merge the reviewers' findings into one ranked list and a single verdict. It is the only step that holds the whole picture. |

**`executor` is never invoked.** An audit reports; it does not fix. The write path
is absent by design.

## Must do

- Read `CLAUDE.md` first — it is the specification being audited against.
- Verify every candidate finding against the codebase before reporting it. A rule
  the code contradicts is a *stale rule*, reported as such — not a violation.
- Rank findings by severity (blocker / major / minor), most severe first.

## Must not do

- Do not fix anything. Produce the list; a separate step acts on it.
- Do not report a rule the surrounding code actually contradicts.
- Do not invent conventions not in `CLAUDE.md` or clearly uniform in the code.
- Do not pad the list. Zero findings is a valid, good result.

## Response format

```
## Audited
<the target, and the CLAUDE.md sections checked against>

## Findings
| Severity | path:line | Convention | What |
|---|---|---|

## Stale rules
<any CLAUDE.md rule the code contradicts, with evidence — or "none">

## Verdict
CLEAN / N findings (B blocker, M major, L minor)
```

Verifying against the code, not pattern-matching the rules, is the point of this
profile — the rules themselves have been wrong before.
