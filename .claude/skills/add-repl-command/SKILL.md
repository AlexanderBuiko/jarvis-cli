---
name: add-repl-command
description: Add a new command to the Jarvis REPL. Use when the task is to add a `jarvis` CLI command, a sub-command, or a new interactive verb. Covers all six registration points, including the two that are easy to miss.
---

# Adding a REPL command

A command in this codebase is registered in **six** places. Five of them are
obvious from reading `commands.py`. Two are routinely missed, including by the
repository's own author — `support`, `quiz` and `files` are all still absent from
`COMMAND_TREE`, so none of them has tab completion.

Work through the list. Do not stop when the command "works": a command that runs
but is invisible to help and autocomplete is not finished.

## The six touchpoints

### 1. Handler — `jarvis/repl/commands.py`

Takes parsed args, **returns a string**. Never prints. Never takes the terminal.

```python
def handle_thing(args: list[str], store: ThingStore | None = None) -> str:
    if not args:
        return "Usage: thing <arg>"
    ...
    return f"Did the thing ({result.id})."
```

Accept the collaborator as an optional argument (`store: ThingStore | None = None`)
so tests can inject a fake without touching `$HOME`.

Put it under a section separator:
`# ── Thing (what it is) ─────────────────────────────`

### 2. Import — `jarvis/repl/loop.py`

Add the handler to the existing `from .commands import (...)` block. Easy to
forget when the handler is written last.

### 3. Dispatch — `jarvis/repl/loop.py::_dispatch`

A flat `if cmd == ...` chain, not a registry. Add a clause **before** the unknown-
command fallback at the end:

```python
if cmd == "thing":
    if not args:
        return handle_thing_list()
    sub = args[0].lower()
    if sub == "add":
        return handle_thing_add(args[1:])
    return "Usage: thing add <text> | thing list"
```

Sub-command dispatch may live here (like `config`, `task`) or inside a single
handler in `commands.py` (like `index`, `mcp`). Both exist. Match whichever
neighbour your command most resembles.

### 4. Help text — `commands.py::HELP_TEXT`

Add to the `Commands` block, aligned with the surrounding entries:

```
  thing add <text>              Save a thing
  thing list                    List saved things
```

### 5. Autocomplete — `jarvis/repl/input.py::COMMAND_TREE`

**This is the one that gets missed.** It is a second registry that `_dispatch`
does not share, so the command works perfectly without it and the omission is
silent.

```python
"thing":   {"add": {}, "list": {}, "delete": {}},
```

An empty dict `{}` marks a leaf. Keep the column alignment of the neighbours.

### 6. Test — `tests/test_<subject>.py`

Ships in the same change. `unittest.TestCase` for stateful subjects with
`setUp`/`tearDown`, plain pytest functions for pure ones — both styles are in use.
Never touch the network. Use `tempfile.TemporaryDirectory()` for real files rather
than mocking `os`.

## If the command needs persistence

Add a `<Thing>Store` in `jarvis/session/`, following `task_store.py` /
`thread_store.py`:

- `def __init__(self, directory: Path | None = None) -> None`
- `self._path = (directory or (Path.home() / ".jarvis")) / _FILENAME`
- JSON under `~/.jarvis/`. No database, no ORM.
- Resolve `Path.home()` at instantiation, not at import, so tests can isolate.
- Reads degrade to a neutral value on a narrow exception tuple:
  `except (json.JSONDecodeError, OSError): return []`
- **Do not add it to `jarvis/session/__init__.py`.** That package exports 2 of its
  6 modules on purpose; the stores are imported directly by their callers.

## Verify

```bash
.venv/bin/ruff check jarvis/          # baseline is 5 pre-existing errors
.venv/bin/python -m pytest -q
```
