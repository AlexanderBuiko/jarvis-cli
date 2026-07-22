# Profile test runs — results

Each profile was run once, prompt verbatim, in a fresh session. The global
selector chose the profile without being told. All three produced a working
result on the first launch, and each surfaced a real defect in the surrounding
material — which is what a good profile is supposed to do.

## Bug Fix — PASS

**Task:** `config set max_tokens -100` is accepted while `temperature 999` is
refused; find why and fix it.

**Chain observed:** reproduce (main) → `planner` (diagnose) → `executor` (fix +
test) → `validator` (verify). Exactly the profile's chain.

| Criterion | Result |
|---|---|
| Root cause, not symptom | ✓ `_parse_param` range-checks only when a validator exists; `max_tokens`/`top_k`/`seed` had none (antipattern 5) |
| Fix at the cause | ✓ added the 3 missing numeric validators, each with a `#` comment |
| Regression test | ✓ `tests/test_config_validation.py`, 7 cases, fails without the fix |
| Suite + lint shown | ✓ 379 passed; ruff 5 (baseline unchanged) |
| Scope discipline | ✓ left the 6 string/bool parser-only keys, noted not changed |

**Bonus finding:** flagged that the documented lint baseline "5 F401" is really
2× F401 + 3× E731. Verified true (the E731s pre-date the fix; the fix added
none). Corrected across the living docs.

## Research — PASS

**Task:** Which REPL commands are not covered by tests?

**Chain observed:** read-only investigation → structured answer. `executor` never
invoked — the read-only guarantee held structurally.

| Criterion | Result |
|---|---|
| Count + list, not prose | ✓ gave both a strict list and a looser one |
| Method stated | ✓ derived commands from `_dispatch`, swept `tests/` for `handle_*` |
| Definition of "covered" stated | ✓ "the suite calls the `handle_*` it dispatches to" |
| Evidence cited | ✓ `loop.py:501-641`, the two covered handlers, the grep |
| No file modified | ✓ |

**Note on the count:** the agent found **14** top-level commands (it counted
`exit`/`quit`) and reported 12 untested under its strict definition, then named
the looser `invariants / mcp / personalize / profile / quiz / session` set that
matches the task's ground truth of 6. The difference is the definition of
"covered", which the agent stated explicitly — an interpretation difference, not
an error. This is the behaviour the task file asked for.

## Convention Audit — PASS (strongest result)

**Task:** Audit `jarvis/config/manager.py` against our conventions.

**Chain observed:** parallel `reviewer` instances → verify against code →
`consolidator`. `executor` never invoked.

| Criterion | Result |
|---|---|
| Real violation found | ✓ `model` and `rag_index` (bare `str`, no validator) |
| No invented findings | ✓ dismissed `Any`, missing `__future__`, line length as in-dialect |
| Verify-against-code | ✓ — see below |

**Why this is the strongest run:** the reviewers disagreed on the key count, so
the profile's "verify against the code, not the rule text" instruction forced a
direct check of the two tables. That check found something the task's own ground
truth had wrong: `_parse_bool` **raises** on bad input, so the four bool
parser-only keys (`rag`, `rag_rewrite`, `rag_cite`, `rag_strict`) are validated by
their parser — a validator entry would be redundant, not missing. Only the two
`str` keys are genuine gaps.

The audit also correctly noticed the file had changed under it (the Bug Fix run,
earlier in the working tree, had already added the numeric validators), and
adjusted the count from the expected 9 to the actual 6.

This falsified my antipattern-5 wording ("a parser-only key accepts garbage
silently"), which is false for a self-validating parser. The rule was refined in
`CLAUDE.md` as a result.
