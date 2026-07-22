# Research — test task

## Prompt (give verbatim)

> Which REPL commands are not covered by tests?

Invoke the `research` agent with this prompt. Answer nothing further.

## Verified ground truth (established before the run)

The 13 commands dispatched in `jarvis/repl/loop.py::_dispatch`:

```
config  help  index  invariants  mcp  personalize
profile  quiz  rag  session  support  task  thread
```

Cross-referenced against every test in `tests/` (searching for `handle_<cmd>` and
the command token). Commands with **no** test reference:

```
invariants   mcp   personalize   profile   quiz   session
```

**6 of 13 untested.** The other 7 (`config`, `help`, `index`, `rag`, `support`,
`task`, `thread`) each appear in at least one test file.

## Success criteria (one run)

1. **A count and a list**, not prose — e.g. "6 of 13: invariants, mcp,
   personalize, profile, quiz, session".
2. **Method stated**: it derived the command set from `_dispatch` and checked each
   against `tests/`, rather than guessing.
3. **Evidence cited** with file paths, so the answer is reproducible.
4. **No file was modified** — trivially guaranteed by the read-only tool grant,
   but the transcript should show it investigated rather than assumed.

A pass is: the list matches ground truth (small boundary differences are
acceptable if justified — e.g. counting a command tested only indirectly), reached
by investigation, on the first run.

## Note on scoring

If the agent's list differs, check *why* before calling it wrong. "Is a command
covered when only its helper is tested, not its dispatch?" is a legitimate
interpretation difference. The agent stating its definition of "covered" counts in
its favour, not against.
