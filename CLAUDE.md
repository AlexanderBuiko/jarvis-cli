# jarvis-cli — Project Rules

**v3** — specialises `~/.claude/CLAUDE.md`. Only what is specific to this
repository lives here; the global file still applies in full.

---

## Stack

| | |
|---|---|
| Language | Python **≥ 3.11**, stdlib-first |
| Runtime deps | `requests`, `prompt-toolkit`, `mcp`, `plotext` — that is the whole list |
| Packaging | legacy `setup.cfg` + one-line `setup.py`. Entry point `jarvis = jarvis.__main__:main` |
| Tests | `pytest` runner, mixed `unittest.TestCase` / plain functions |
| LLM providers | OpenRouter (cloud, default), Ollama (local) |
| Persistence | JSON files under `~/.jarvis/`. **No database, no ORM, no SQL** |
| Frameworks | none. No Django, no FastAPI, no Pydantic, no SQLAlchemy, no rich |

`sentence-transformers` is an optional extra (`pip install -e .[rerank]`) and
must never become a hard import.

## Architecture

An interactive LLM assistant built on **abstractions first, providers second**.
Everything above the seam talks to a Protocol; concrete clients plug in beneath.

```
jarvis/__main__.py        entry point — wires router, gateways, agent, REPL
    │
    ├── repl/             ALL user-facing I/O. The only package that prints.
    │     loop.py         REPL loop + `_dispatch` command chain (the driver)
    │     commands.py     command handlers — take args, RETURN a string
    │     input.py        prompt-toolkit input, COMMAND_TREE autocomplete
    │
    ├── agent.py          JarvisAgent — conversation orchestration
    ├── llm/              engine.py (LLMEngine Protocol), router.py, gateway.py
    ├── openrouter/       OpenRouterClient  ─┐ satisfy LLMEngine
    ├── ollama/           OllamaClient      ─┘ structurally
    │
    ├── pipeline/         task FSM: fsm.py, base.py, stages.py, orchestrator.py,
    │                     invariants.py, swarm.py, parallel.py
    ├── mcp/              MCP client side: registry, provider, permissions gate
    ├── mcp_servers/      MCP server side: git_server.py, files_server.py
    ├── indexing/         embeddings, chunking, JSON vector store
    ├── rag/              retrieval-augmented generation, eval, rerank
    ├── session/          stores: thread, task, profile, invariant
    ├── config/           ConfigManager (runtime params), env_file loader
    ├── review/           standalone `python -m jarvis.review` CI entry point
    ├── smoke/            Level-2 UI smoke: pty-drives the real REPL, platform-agnostic
    └── web/              minimal browser UI (`python -m jarvis.web`) over the same _dispatch
```

**Two test levels.** Level 1 is code — `pytest` over business logic, faked at the
`LLMEngine` seam, no network. Level 2 is UI smoke — `python -m jarvis.smoke`
launches the real `jarvis` in a pty and drives it like a user, capturing each
step's terminal output as a "screenshot". `python scripts/qa_report.py` runs both
and emits one report (the CI gate in `ai-review.yml`). The smoke runner talks to a
`SmokeAdapter` Protocol, so a scenario is a command string that runs on any
platform: the **cli** adapter pty-drives the REPL (deterministic, always gated),
the **web** adapter ([jarvis/smoke/web.py](jarvis/smoke/web.py)) drives the web UI
in headless Chromium via Playwright (optional `web` extra — skipped when absent).
A mobile adapter plugs in the same way.

**Layering rule.** `repl/` may import anything. Library packages must not import
`repl/`. Library packages must not print.

### Task stages — this project's FSM is the source of truth

The global stage vocabulary is **implemented in code** here, at
[jarvis/pipeline/fsm.py:16](jarvis/pipeline/fsm.py:16):

```
clarification → planning → execution → validation → done
```

`ALLOWED_TRANSITIONS` and `resolve_transition()` are the enforcement point. When
you work on task-state code, use these exact stage names — never invent
`research`, `implement`, `report`. Transitions go through
`TaskStore.advance_stage`, never by assigning `task.stage` directly.

## Profiles, subagents and skills

Three layers. The global `CLAUDE.md` **selects a profile**; the profile
(`~/.claude/profiles/`) is a **workflow** that orchestrates **subagents**
(`.claude/agents/`), which do the work. A profile is not a subagent.

**Subagents — the workers.** They mirror the application's own pipeline roles
one-to-one, so the process you follow and the process Jarvis runs use the same
vocabulary.

| Agent | Mirrors | Tools |
|---|---|---|
| `planner` | `PlannerAgent` ([stages.py:137](jarvis/pipeline/stages.py:137)) | read-only |
| `executor` | `ExecutorAgent` ([stages.py:189](jarvis/pipeline/stages.py:189)) | read + write |
| `validator` | `ValidatorAgent` ([stages.py:261](jarvis/pipeline/stages.py:261)) | read-only **by design** |
| `reviewer` | the swarm panel ([swarm.py](jarvis/pipeline/swarm.py)) | read-only |
| `consolidator` | the swarm consolidator | read-only |

- **`validator` has no edit tools.** A role that reports must not be able to
  change what it reports on.
- **`reviewer` instances never see each other.** Run several in parallel with
  different perspectives, then pass every opinion to `consolidator` — the only one
  that knows the goal. This is the shape in `swarm.py`, followed exactly.

**Profiles — the workflows.** The global selector routes to `bug-fix`, `research`
or `convention-audit`. Those profiles are stack-agnostic; this project supplies
the concrete commands they invoke:

| Where the profile says… | In this project, use |
|---|---|
| run the test suite | `.venv/bin/python -m pytest -q` |
| run the linter | `.venv/bin/ruff check jarvis/` — baseline is **5** pre-existing errors (2× `F401` in `task_store.py`, 3× `E731` in `__main__.py` + `rag/evaluation.py`); only new errors count |
| confirm imports | `.venv/bin/python -c "import jarvis.repl.loop"` |
| the config-param audit | a **value-accepting** parser (`int`/`float`/`str`) in `_PARAM_PARSERS` with no `_PARAM_VALIDATORS` entry ([config/manager.py](jarvis/config/manager.py)) — antipattern 5. A self-validating parser like `_parse_bool` needs no validator. |

Their "read-only" steps (`research`, `convention-audit`) never invoke `executor`,
so "must not change code" is enforced by the chain, not by a rule the model must
remember.

Skills carry the **procedural** knowledge — the step-by-step recipes — while this
file carries the **conventions**. That split is on purpose: a recipe is needed
only when you are performing that specific task, so it is loaded on demand instead
of occupying the system prompt on every turn.

| Skill | Use when |
|---|---|
| `add-repl-command` | adding a CLI command, sub-command or interactive verb |
| `add-mcp-server` | adding an MCP server, or a tool to an existing one |
| `update-smoke` | after a feature lands, refresh smoke scenarios and rerun the QA gate |

## Naming

| Kind | Rule | Examples |
|---|---|---|
| Module files | one lowercase word; underscores only when unavoidable | `client.py`, `store.py`, `registry.py`, `task_store.py` |
| HTTP / connection clients | suffix `Client` | `OpenRouterClient`, `MCPClient` |
| Persistence | suffix `Store` | `SessionStore`, `TaskStore`, `IndexStore` |
| Pipeline stage agents | suffix `Agent` | `PlannerAgent`, `ValidatorAgent` |
| Result carriers | suffix `Result` / `Report` | `StageResult`, `EvalReport` |
| Services | suffix `Service` | `ConversationService` |
| Protocols | bare capability noun, no suffix | `LLMEngine`, `Embedder`, `Reranker` |
| Private helpers | leading `_` | `_resolve`, `_git`, `_raise_for_status` |
| Constants | `UPPER_SNAKE`, `_UPPER_SNAKE` if private | `DEFAULT_MODEL`, `_SKIP_DIRS` |
| Env vars | `JARVIS_*` (exception: `OPENROUTER_API_KEY`) | `JARVIS_FILES_ROOT` |
| Tests | `tests/test_<subject>.py`, test names are full sentences | `test_unauthorised_write_is_queued_not_run` |

## Patterns

**Protocol as seam.** Cross-cutting capabilities are `@runtime_checkable`
Protocols. Implementations satisfy them **structurally — never inherit**. Every
Protocol has a Fake for tests.

**Imports are relative** inside the package: `from ..openrouter.client import
Completion`. Never `from jarvis.openrouter.client import ...`.

**Typing** is PEP 604/585 native: `str | None`, `list[dict]`, `dict[str, Any]`.
Never `Optional[...]`, never `List[...]`. `-> None` is written explicitly on
every `__init__`.

**Data carriers — the split depends on whether the value is persisted.**

*In-memory* carriers are `@dataclass`, or `NamedTuple` when immutable: results,
reports, verdicts, configs, anything passed between functions. All 25 of the
codebase's dataclasses are this kind — `StageVerdict`, `StageResult`,
`EvalReport`, `Completion`, `Chunk`, `ReviewOpinion`. Field documentation goes in
a trailing `#` comment on the field, not in the docstring.

*Persisted* records that round-trip through a `Store` to a JSON file are plain
`dict`. `TaskStore.load() -> dict | None`, `ThreadStore.list_all() -> list[dict]`,
and `task: dict` throughout `pipeline/`. There is **no** dataclass in `session/`
that survives a restart — `SessionEntry` looks like one but is held in memory and
never written.

So a new `Store` returns `dict`, and the thing it hands to a caller for display or
computation may be a dataclass. Do not "improve" a persisted record into a
dataclass: it adds a serialisation layer the rest of the codebase does not have.

**`from __future__ import annotations`** goes in every *new* module under
`jarvis/`. Do not retrofit it into older modules as a drive-by change, and do
not add it to tests — only 1 of 36 test modules uses it.

**Config resolution order** is always `explicit argument → env var → hardcoded
default`, resolved in the constructor:
```python
self.url = (url or os.environ.get("JARVIS_OLLAMA_URL") or "http://localhost:11434").rstrip("/")
```

**Two output channels, never mixed.** User-facing text is `print()`, and only in
the UI layer and process entry points — `jarvis/repl/`, `jarvis/__main__.py`,
`jarvis/mcp/cli.py`, `jarvis/review/__main__.py`. Every other module returns
strings. Diagnostics are stdlib `logging` with dotted named loggers
(`logging.getLogger("jarvis.mcp.config")`) and `%s` lazy formatting.

**Errors.** Custom exceptions are defined in the module that raises them, not in
a shared `errors.py` — there are only two in the codebase. Provider and network
failures are wrapped into `RuntimeError` with a human-readable message and
always `raise ... from exc`. Non-fatal paths catch a *narrow* exception tuple and
return a neutral value.

**Section separators** divide long modules:
`# ── Title ─────────────────────────────` padded toward column 80.

**Docstrings**: one-line summary, blank line, free prose explaining *why this
design and not the obvious alternative*. No `Args:` / `Returns:` / `:param:`
sections anywhere in this codebase. Return values are described inline in the
summary line. Identifiers get ``double-backtick`` markup.

---

## Good examples — write code like this

### 1. A Protocol seam ([jarvis/llm/engine.py:20](jarvis/llm/engine.py:20))

```python
@runtime_checkable
class LLMEngine(Protocol):
    """The contract every LLM provider implementation must satisfy."""

    def complete(self, messages: list[dict], params: dict[str, Any]) -> Completion:
        """Send a chat-completion request and return the Completion."""
        ...

    def get_pricing(self, model_id: str) -> tuple[float | None, float | None]:
        """Return (input_$/M_tokens, output_$/M_tokens), or (None, None)."""
        ...
```
Narrow contract, one-line docstring per method, return shape described inline.

### 2. A factory with deliberate function-local imports ([jarvis/llm/router.py:33](jarvis/llm/router.py:33))

```python
def make_engine(provider: str | None = None) -> LLMEngine:
    """Build a concrete engine. Resolution: arg → ``JARVIS_LLM_PROVIDER`` → openrouter."""
    provider = (provider or os.environ.get("JARVIS_LLM_PROVIDER") or "openrouter").lower()
    if provider == "openrouter":
        from ..openrouter.client import OpenRouterClient
        return OpenRouterClient()
    if provider == "ollama":
        from ..ollama.client import OllamaClient
        return OllamaClient()
    raise ValueError(
        f"Unknown LLM provider '{provider}'. Use one of: openrouter, ollama."
    )
```
Imports are inside the branches on purpose — running local must not require
`OPENROUTER_API_KEY`. The error message enumerates the valid values.

### 3. A security boundary, documented as one ([jarvis/mcp_servers/files_server.py:66](jarvis/mcp_servers/files_server.py:66))

```python
def _resolve(path: str) -> str:
    """Resolve ``path`` (repo-relative or absolute) to a realpath **inside the root**.

    Raises ``ValueError`` if it escapes the root — the confinement boundary.
    """
    root = _root()
    candidate = path if os.path.isabs(path) else os.path.join(root, path)
    resolved = os.path.realpath(candidate)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError(f"path '{path}' is outside the project root")
    return resolved
```
`realpath` before the check defeats symlink escape; the `root + os.sep` guard
defeats the `/root-evil` prefix trick. The docstring names the invariant.

### 4. Exception + dataclass with inline field comments ([jarvis/review/client.py:19](jarvis/review/client.py:19))

```python
class ReviewClientError(Exception):
    """A hard failure the CI step should surface (non-zero exit)."""


@dataclass
class ReviewContext:
    """Everything needed to review one PR, resolved from CLI args or the Action env."""

    repo: str | None          # "owner/name"
    pr_number: int | None
    base: str                 # git ref to diff against (e.g. "origin/main")
    head: str                 # git ref of the PR head (e.g. "HEAD")
```

### 5. FSM enforcement in code, not in the prompt ([jarvis/pipeline/fsm.py:38](jarvis/pipeline/fsm.py:38))

```python
def resolve_transition(current: str, target: str | None) -> str:
    """Validate and resolve a transition, returning the resulting stage.

    ``target`` defaults to the forward edge when omitted. Raises ValueError if
    the stage is terminal or the requested transition is not permitted — this is
    the code-level guard that makes "the assistant cannot skip a stage" real.
    """
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if not allowed:
        raise ValueError(f"task is already in the terminal stage '{current}'")
    if target is None:
        target = allowed[0]
    if target not in allowed:
        raise ValueError(
            f"cannot move {current} → {target} (allowed: {', '.join(allowed)})"
        )
    return target
```
The model *signals*; code *decides*. Keep policy in code and testable.

---

## Antipatterns — prohibited

### 1. `print()` in a library module
Library modules **return strings**; the UI layer and entry points print them.
A `print()` in `jarvis/rag/`, `jarvis/pipeline/`, `jarvis/indexing/`,
`jarvis/session/` … is a layering violation — it makes the function untestable
and unusable from the non-REPL entry points. (Printing *is* correct inside
`jarvis/repl/`, `__main__.py` and `mcp/cli.py` — those are the UI layer.)

```python
# NO — in jarvis/indexing/pipeline.py
print(f"Indexed {n} chunks")

# YES
return f"Indexed {n} chunks"          # caller in repl/commands.py prints it
logger.info("indexed %d chunks", n)   # diagnostics go to the named logger
```

### 2. f-strings inside logging calls
Formats eagerly even when the level is disabled, and breaks log aggregation.

```python
logger.warning(f"skipping {entry}: {exc}")        # NO
logger.warning("skipping invalid entry %r: %s", entry, exc)   # YES
```

### 3. Inheriting from a Protocol, or `Optional` / `List` typing

```python
class OllamaClient(LLMEngine):                    # NO — defeats structural typing
    def complete(self, m: List[dict], p: Optional[dict]) -> Completion:   # NO
        ...

class OllamaClient:                               # YES — satisfies it structurally
    def complete(self, messages: list[dict], params: dict[str, Any]) -> Completion:
        ...
```
Also prohibited: absolute intra-package imports (`from jarvis.llm.engine import
…` instead of `from ..llm.engine import …`), and `Any` as a lazy return type.
`Any` is allowed **only** for untyped provider payloads and heterogeneous config
dicts.

### 4. Raising out of an MCP tool
A tool that raises kills the LLM's turn with an opaque failure. Tools degrade to
a readable string, always.

```python
@mcp.tool()
def read_file(path: str) -> str:
    return open(_resolve(path)).read()     # NO — ValueError escapes to the model

@mcp.tool()
def read_file(path: str) -> str:
    """Read a file inside the project root."""
    try:
        return open(_resolve(path)).read()
    except Exception as exc:
        return f"error: {exc}"             # YES
```
Mutating tools additionally take `dry_run: bool = False` and return the unified
diff without touching disk when it is set.

### 5. A half-registered config parameter
`config set <key>` is driven by two tables in
[jarvis/config/manager.py](jarvis/config/manager.py). A key whose parser accepts
a range of values (`int`, `float`, bare `str`) but has no `_PARAM_VALIDATORS`
entry takes garbage silently — that is the antipattern. Add to **both**, with the
`#` comment explaining the knob.

The exception is a parser that **already rejects bad input by raising** — e.g.
`_parse_bool`, which raises on anything but true/false. Parsing *is* validation
there, so a validator entry would be redundant, not missing. Do not flag those.
So the real gap is a value-accepting parser (`int`/`float`/`str`) with no
validator; a self-validating parser is complete on its own. (`SUPPORTED_PARAMS`
is derived from the parsers, so a validator-only entry is dead code regardless.)

Same failure mode elsewhere: **partially registering any feature**. This
codebase registers things in more than one place, and a feature that works but
is invisible (missing from help text, from autocomplete, from `__all__`) is
incomplete.

### 6. Network or real LLM calls in tests
Tests never touch the network. Fake at the `LLMEngine` seam with
`tests/fake_engine.FakeEngine`, or `monkeypatch.setattr(requests, "post", …)`
with a local `_FakeResp`. Real filesystem via `tempfile.TemporaryDirectory()` is
fine and preferred over mocking `os`.

---

## File template

```python
"""
<module> — one-line statement of what this is.

Why it exists and why it is shaped this way. Name the obvious alternative and
say why it was rejected. This paragraph is the most valuable part of the file.
"""

from __future__ import annotations

import json                      # stdlib, alphabetical
import os
from dataclasses import dataclass

import requests                  # third-party

from .config import ServerConfig # local — always relative
from ..llm.engine import LLMEngine


# Explain any constant that is not self-evident.
DEFAULT_TIMEOUT_S = 30
_SKIP = frozenset({"a", "b"})    # private → leading underscore


class ThingError(RuntimeError):
    """Raised when <specific condition>."""


@dataclass
class ThingResult:
    """What one <operation> produced."""

    name: str
    count: int          # trailing comment documents the field
    detail: str | None = None


# ── Main class ────────────────────────────────────────────────────────────────


class ThingClient:
    """One-line summary.

    Longer prose on behaviour, failure modes and precedence rules.
    """

    def __init__(self, url: str | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self.url = (url or os.environ.get("JARVIS_THING_URL") or "http://localhost:9").rstrip("/")
        self.timeout = timeout

    def fetch(self, key: str) -> ThingResult:
        """Return the <thing> for ``key``, or raise ThingError if unreachable."""
        try:
            resp = requests.get(f"{self.url}/{key}", timeout=self.timeout)
        except requests.RequestException as exc:
            raise ThingError(f"thing service unreachable at {self.url}") from exc
        return ThingResult(name=key, count=resp.json()["count"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _normalise(raw: str) -> str:
    """Private helpers go last."""
    return raw.strip().lower()
```

**Package `__init__.py`** — **not universal; follow the package you are in.**
`llm/`, `mcp/`, `indexing/`, `rag/`, `review/` re-export their public surface.
`session/` deliberately does not — it holds 6 modules and exports 2, because the
stores are imported directly by their callers. `pipeline/` has no `__all__` at
all. Adding a new module to a package that does not re-export is **not** a
missing registration; leave its `__init__.py` alone.

Where a package does re-export, the shape is: docstring, flat relative imports,
explicit `__all__` mirroring import order (not alphabetical):

```python
"""jarvis.thing — one-line purpose."""

from .client import ThingClient, ThingError
from .store import ThingStore

__all__ = ["ThingClient", "ThingError", "ThingStore"]
```

For a package with more than ~3 modules, the docstring carries an aligned file
map — see [jarvis/mcp/__init__.py](jarvis/mcp/__init__.py) and
[jarvis/indexing/__init__.py](jarvis/indexing/__init__.py).
