# calckit — sandbox rules (for the execution loop)

A tiny throwaway toolkit the harness works on. Enough context that each task is
self-sufficient (no need to ask the operator).

## Layout
- `calckit/core.py` — `add`, `subtract`, `multiply`, `divide`
- `calckit/stats.py` — `mean`, `median`
- `calckit/textutils.py` — `slugify`
- `tests/` — pytest tests; `calckit` imports from the repo root (cwd)

## Validate
Run the tests — this is the pass/fail gate:
```
.venv/bin/python -m pytest -q
```
No linter, no type checker. Keep it stdlib-only, Python 3.11+.

## Conventions
- One change per task. A behavioural change ships with a test in the same commit.
- Match the style of the file you edit. Do not reformat unrelated code.
- If a detail is unspecified, choose a sensible default and note it in the commit
  body — do not stop to ask.
