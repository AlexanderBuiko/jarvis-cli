---
name: add-mcp-server
description: Add a new MCP server to jarvis/mcp_servers/, or add a tool to an existing one. Use when the task involves exposing local capabilities to the LLM as MCP tools. Covers the error contract, root confinement and registration.
---

# Adding an MCP server

Two exist: `git_server.py` (67 lines, 1 tool) and `files_server.py` (379 lines,
8 tools). Both use `FastMCP` over stdio. Copy their shape.

## Minimal server

```python
"""
<name>_server — one line on what this exposes.

Why these tools and not others. Name the rejected alternative.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("thing")          # MUST match the "name" in servers.json


@mcp.tool()
def do_thing(path: str, dry_run: bool = False) -> str:
    """Read the thing at ``path``.

    This docstring is sent to the LLM as the tool description. Write it for the
    model, not for a developer.
    """
    try:
        ...
        return result
    except Exception as exc:
        return f"error: {exc}"


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

## The error contract — the rule that matters most

**A tool never raises.** An exception escaping a tool kills the model's turn with
an opaque failure it cannot recover from. Every tool degrades to a readable
string:

```python
return f"error: {exc}"
```

This is the inverse of normal Python practice, and it is deliberate. The model
reads the string and can retry or explain; it cannot read a traceback.

## Root confinement — for anything touching the filesystem

Copy `_resolve` from `jarvis/mcp_servers/files_server.py:66`:

```python
def _resolve(path: str) -> str:
    root = _root()
    candidate = path if os.path.isabs(path) else os.path.join(root, path)
    resolved = os.path.realpath(candidate)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError(f"path '{path}' is outside the project root")
    return resolved
```

Two details carry the security, and both are easy to drop:

- `realpath` **before** the check — otherwise a symlink escapes the root.
- `root + os.sep` — otherwise `/project-evil` passes the prefix test for `/project`.

The root comes from an env var with a cwd fallback:
`os.environ.get("JARVIS_THING_ROOT", "").strip() or os.getcwd()`.

Every tool calls `_resolve` and converts its `ValueError` into `error: ...`.

## Mutating tools

Any tool that writes takes `dry_run: bool = False` and, when set, returns the
unified diff **without touching disk**.

Writes also pass through the permission gate in `jarvis/mcp/permissions.py`. Add
the tool's bare name to `DEFAULT_MUTATING` there if it mutates — matching is on
the basename, so both `thing__write` and `thing.write` route correctly. An
unauthorised write is **queued, not denied**; the REPL drains the queue after the
turn.

## Registration

`servers.json` is **gitignored**. Update `servers.json.example` too, or the entry
is invisible to everyone else.

```json
{ "name": "thing", "transport": "stdio",
  "command": "python3", "args": ["-m", "jarvis.mcp_servers.thing_server"] }
```

Resolution order is `$JARVIS_SERVERS_FILE` → `./servers.json` →
`~/.jarvis/servers.json`. Secrets go in as `${VAR}` and are expanded from the
environment; an unresolved `${...}` causes the value to be dropped, not
substituted literally.

One malformed entry is skipped with a warning, not fatal — so a typo means your
server silently does not load. Check `mcp list` after registering.

## Test

`tests/test_<name>_mcp_server.py`. Call the tool functions directly; do not start
a server. Use `tempfile.TemporaryDirectory()` for the root. Test the confinement
boundary explicitly — `..` traversal and a symlink pointing outside both belong in
the test.

```bash
.venv/bin/ruff check jarvis/          # baseline is 5 pre-existing errors
.venv/bin/python -m pytest -q
```
