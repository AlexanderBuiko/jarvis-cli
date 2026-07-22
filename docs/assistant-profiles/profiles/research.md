# Profile: Research

A workflow for "answer a question about the codebase". This file is the **chain**:
it says which subagents run and why. It is not a subagent itself.

Selected when the request is a question about how the code is — how something
works, where something lives, what is or is not covered — and nothing is claimed
to be broken. The output is understanding, not a change.

## The chain

| Step | Subagent | Purpose |
|---|---|---|
| 1. Investigate | `planner` (read-only use) or direct read-only exploration | Locate the real code, read the narrowest slice that answers the question, gather ground truth with read-only commands. |
| 2. Answer | *(main agent)* | Assemble a structured, cited answer. Every fact traces to a `path:line`. |

**`executor` is never invoked in this chain.** That is what makes "do not change
the code" structural rather than a rule to remember — the only writing subagent is
simply not part of the route.

## Must do

- Investigate before answering; never answer from a guess about how the project
  "probably" works.
- Verify every claim against the code. An unverifiable claim is labelled unverified
  or left out.
- Report counts as counts and lists as lists ("6 of 13: a, b, c…"), not prose.
- Use read-only commands (search, log, test-collection) to establish ground truth.

## Must not do

- Do not change any code, run tests to mutate state, install anything, or write
  files.
- Do not present a guess as a finding.
- Do not pad. If the answer is three files and one conclusion, that is the whole
  response.

## Response format

```
## Question
<restated in one line, with the interpretation chosen if it was ambiguous>

## Answer
<the direct answer first — the count, the list, the conclusion>

## Evidence
| Claim | Where |
|---|---|

## Files examined
<so the answer is reproducible>

## Caveats
<what could not be verified, or "none">
```

The Answer block comes first and stands alone. The proof follows it.
