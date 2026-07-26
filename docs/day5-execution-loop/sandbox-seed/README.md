# calckit (execution-loop sandbox)

A throwaway Python toolkit the Day-5 execution loop operates on. It has three
modules and known gaps that the task pool targets:

- `calckit/core.py` — `add`, `subtract`, `multiply`, `divide`
- `calckit/stats.py` — `mean`, `median`
- `calckit/textutils.py` — `slugify`

Run the tests from this directory:

```bash
python -m pytest -q
```

This is the **seed**. The runbook copies it to a scratch directory before the
loop runs, so the assistant's autonomous commits never touch the jarvis-cli repo.
