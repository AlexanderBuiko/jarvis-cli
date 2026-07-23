# Convention examples & templates

Worked illustrations of the house style. `CLAUDE.md` states the rules; this file
shows them. Read it when writing a new module — it is not loaded into every turn,
so it costs nothing until you open it.

## Good examples — write code like this

### 1. A Protocol seam ([jarvis/llm/engine.py:20](../jarvis/llm/engine.py))

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

### 2. A factory with deliberate function-local imports ([jarvis/llm/router.py:33](../jarvis/llm/router.py))

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

### 3. A security boundary, documented as one ([jarvis/mcp_servers/files_server.py:66](../jarvis/mcp_servers/files_server.py))

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

### 4. Exception + dataclass with inline field comments ([jarvis/review/client.py:19](../jarvis/review/client.py))

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

### 5. FSM enforcement in code, not in the prompt ([jarvis/pipeline/fsm.py:38](../jarvis/pipeline/fsm.py))

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

## Antipattern illustrations

The prohibitions are listed in `CLAUDE.md`; here is the NO/YES code for each.

**1. `print()` in a library module**
```python
# NO — in jarvis/indexing/pipeline.py
print(f"Indexed {n} chunks")

# YES
return f"Indexed {n} chunks"          # caller in repl/commands.py prints it
logger.info("indexed %d chunks", n)   # diagnostics go to the named logger
```

**2. f-strings inside logging calls**
```python
logger.warning(f"skipping {entry}: {exc}")        # NO
logger.warning("skipping invalid entry %r: %s", entry, exc)   # YES
```

**3. Inheriting from a Protocol, or `Optional` / `List` typing**
```python
class OllamaClient(LLMEngine):                    # NO — defeats structural typing
    def complete(self, m: List[dict], p: Optional[dict]) -> Completion:   # NO
        ...

class OllamaClient:                               # YES — satisfies it structurally
    def complete(self, messages: list[dict], params: dict[str, Any]) -> Completion:
        ...
```

**4. Raising out of an MCP tool**
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

**Package `__init__.py`** — where a package re-exports, the shape is: docstring,
flat relative imports, explicit `__all__` mirroring import order (not
alphabetical):

```python
"""jarvis.thing — one-line purpose."""

from .client import ThingClient, ThingError
from .store import ThingStore

__all__ = ["ThingClient", "ThingError", "ThingStore"]
```

For a package with more than ~3 modules, the docstring carries an aligned file
map — see [jarvis/mcp/__init__.py](../jarvis/mcp/__init__.py) and
[jarvis/indexing/__init__.py](../jarvis/indexing/__init__.py).
