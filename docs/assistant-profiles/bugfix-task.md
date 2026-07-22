# Bug Fix — test task

## Prompt (give verbatim, no hints)

> In the Jarvis REPL, `config set max_tokens -100` is accepted without complaint
> and then requests misbehave. But `config set temperature 999` is correctly
> rejected with an error. A negative `max_tokens` should be rejected the same way.
> Find out why it is not, and fix it.

Invoke the `bug-fix` agent with this prompt. Answer nothing further.

## Verified ground truth (established before the run)

`jarvis/config/manager.py` drives `config set` from two tables. `_PARAM_PARSERS`
(24 entries) converts the string to a typed value; `_PARAM_VALIDATORS` (15
entries) range-checks it. `_parse_param` only checks a validator **if one
exists** — a missing entry means the value is accepted unchecked.

Nine params parse but have no validator:

```
max_tokens, model, rag, rag_cite, rag_index, rag_rewrite,
rag_strict, seed, top_k
```

Reproduction confirmed:

```
config set temperature 999   -> rejected: "temperature must be between 0.0 and 2.0"
config set max_tokens -100   -> ACCEPTED, runtime = -100
config set max_tokens 0      -> ACCEPTED, runtime = 0
config set top_k -5          -> ACCEPTED, runtime = -5
```

This is the exact shape of `CLAUDE.md` antipattern 5 ("a half-registered config
parameter"), present in the live code.

## Success criteria (one run)

1. **Root cause named**, not the symptom: the missing `_PARAM_VALIDATORS` entry
   and `_parse_param`'s conditional check — not "negative numbers are bad".
2. **Fix at the cause:** a validator for `max_tokens` (`> 0`), ideally covering
   the sibling gaps it touches (`top_k`, `seed`) with a documented `#` comment per
   `CLAUDE.md`.
3. **Test added** that fails without the fix and passes with it.
4. **Full suite + ruff run**, output shown; lint stays at the 5-error baseline.
5. Reported in the found / fixed / checked format, every "checked" row backed by
   real output.

A pass is: correct cause on the first launch, a working fix, and the suite green —
all shown, not asserted.
