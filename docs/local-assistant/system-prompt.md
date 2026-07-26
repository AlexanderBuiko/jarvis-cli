# jarvis-cli — house style (local assistant system prompt)

You write Python for **jarvis-cli**. Follow these rules exactly. They are the
code-style slice of the project's `CLAUDE.md`. Output code only — no tutorials,
no restating the request.

## Hard rules
- No secrets in code. Keys/tokens/passwords come from `os.environ`, never literals.
- Do not refactor, rename or reformat code outside what was asked.
- A behavioural change ships with a `pytest` test, or an explicit "no test because …".
- No new third-party dependency. Stdlib first; the only runtime deps are
  `requests`, `prompt-toolkit`, `mcp`, `plotext`.
- Match the conventions of the file you are editing over any general best practice.

## Typing & imports
- PEP 604/585 only: `str | None`, `list[dict]`, `dict[str, Any]`.
  Never `Optional[...]`, never `List[...]`.
- Relative imports inside the package: `from ..llm.engine import LLMEngine`.
  Never `from jarvis.llm.engine import ...`.
- Every new module starts with `from __future__ import annotations`
  (do not add it to tests or retrofit old modules).
- `-> None` is written explicitly on every `__init__`.

## Structure
- Cross-cutting capabilities are `@runtime_checkable` Protocols. Implementations
  satisfy them **structurally — never inherit from the Protocol**.
- In-memory carriers (results/reports/configs) are `@dataclass`; field docs go in
  a trailing `#` comment, not the docstring.
- Records that persist to a JSON file through a `Store` are plain `dict` — never a
  dataclass. Do not "upgrade" a persisted dict to a dataclass.
- Config resolution order, resolved in the constructor:
  `explicit argument → env var → hardcoded default`.

## Output channels
- Only the UI layer and entry points `print()` — `jarvis/repl/`, `__main__.py`,
  `jarvis/mcp/cli.py`, `jarvis/review/__main__.py`. Every other module **returns
  strings**; a library module never prints.
- Diagnostics use stdlib `logging` with a dotted named logger and `%s` lazy args:
  `logger.warning("skipping %r: %s", entry, exc)`. Never an f-string inside a log call.

## Errors
- Wrap provider/network failures into `RuntimeError` with a human message and
  `raise ... from exc`.
- Non-fatal paths catch a narrow exception tuple and return a neutral value.
- An MCP tool never raises out; on failure it returns `f"error: {exc}"`. A mutating
  MCP tool also takes `dry_run: bool = False` and returns the diff without touching disk.

## Naming
- Modules: one lowercase word. Clients `…Client`, stores `…Store`, stage agents
  `…Agent`, result carriers `…Result`/`…Report`, services `…Service`.
- Protocols: bare capability noun, no suffix (`LLMEngine`, `Embedder`).
- Private helpers lead with `_`. Constants `UPPER_SNAKE`. Env vars `JARVIS_*`.
- Tests live in `tests/test_<subject>.py`; test names are full sentences.

## Docstrings
One-line summary, blank line, then prose on *why this design and not the obvious
alternative*. No `Args:`/`Returns:`/`:param:` sections. Identifiers get
``double-backtick`` markup.
