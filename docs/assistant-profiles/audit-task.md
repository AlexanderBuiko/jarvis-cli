# Convention Audit — test task

## Prompt (give verbatim)

> Audit `jarvis/config/manager.py` against our conventions.

Invoke the `convention-audit` agent with this prompt. Answer nothing further.

## Why this target

`manager.py` is a good audit subject because it contains a **real** convention
violation — the nine config params with a parser but no validator, which is
`CLAUDE.md` antipattern 5 by name. A competent audit should surface it. The file
is otherwise clean, so the run also tests whether the agent pads the list with
invented findings (it should not).

## Verified ground truth (established before the run)

- **Real finding:** `max_tokens, model, rag, rag_cite, rag_index, rag_rewrite,
  rag_strict, seed, top_k` are in `_PARAM_PARSERS` but not `_PARAM_VALIDATORS`
  (`jarvis/config/manager.py`). This is antipattern 5.
- **Not findings** (these match the dialect, so flagging them would be wrong):
  - `manager.py` has no `from __future__ import annotations` — it is an existing
    module, and the rule forbids retrofitting.
  - It uses `Any` in `_parse_param` / the parser tables — allowed for
    heterogeneous config values by the rules.
  - Line lengths reach ~100 chars — the codebase runs to 100, so this is in-dialect.

## Success criteria (one run)

1. **The validator gap is reported** as the/a finding, correctly attributed to
   antipattern 5.
2. **No invented findings**: the `Any` usage, the missing `__future__` import and
   the line length are NOT flagged, or are explicitly dismissed as in-dialect.
3. Output in the findings / stale-rules / verdict format.

A pass is: the real violation found, no false positives, on the first run. The
strongest possible result is that it also notes the missing-`__future__` and `Any`
cases in "stale rules" or dismisses them explicitly — showing it verified against
the code rather than pattern-matching the rules.
