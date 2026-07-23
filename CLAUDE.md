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

## Good examples & file template

Worked illustrations of the house style — the Protocol seam, the
function-local-import factory, the `_resolve` security boundary, the dataclass
with inline field comments, the FSM guard, plus the module and package
`__init__.py` templates — live in [docs/conventions.md](docs/conventions.md).
Read it when writing a new module. It is not loaded every turn, so it is free
until opened.

## Antipatterns — prohibited

NO/YES code for each is in [docs/conventions.md](docs/conventions.md).

1. **`print()` in a library module.** Library modules return strings; only the UI
   layer and entry points print — `jarvis/repl/`, `__main__.py`, `mcp/cli.py`,
   `review/__main__.py`. Diagnostics go to a dotted `logging` logger.
2. **f-strings inside `logging` calls.** Use `%s` lazy args:
   `logger.warning("skipping %r: %s", entry, exc)`.
3. **Inheriting from a Protocol; `Optional`/`List` typing; absolute intra-package
   imports; `Any` as a lazy return.** Satisfy Protocols structurally; PEP 604/585
   (`str | None`, `list[dict]`); relative imports (`from ..llm.engine import …`);
   `Any` only for untyped provider payloads and heterogeneous config dicts.
4. **Raising out of an MCP tool.** Degrade to `f"error: {exc}"`. Mutating tools
   also take `dry_run: bool = False` and return the diff without touching disk.
5. **A half-registered config parameter.** A value-accepting parser
   (`int`/`float`/bare `str`) in `_PARAM_PARSERS` with no `_PARAM_VALIDATORS`
   entry takes garbage silently — add both, with a `#` comment. A parser that
   *raises* on bad input (e.g. `_parse_bool`) is self-validating and needs no
   validator. Same failure = registering a feature in only some of its places
   (help text, autocomplete, `__all__`).
6. **Network or real LLM calls in tests.** Fake at the `LLMEngine` seam
   (`tests/fake_engine.FakeEngine`) or `monkeypatch.setattr(requests, "post", …)`;
   real files via `tempfile.TemporaryDirectory()`, never by mocking `os`.

## Package `__init__.py` — not universal

`llm/`, `mcp/`, `indexing/`, `rag/`, `review/` re-export their public surface via
`__all__`. `session/` deliberately does not — 6 modules, 2 exported; `pipeline/`
has no `__all__` at all. Adding a module to a non-re-exporting package is **not** a
missing registration; leave its `__init__.py` alone. Re-export shape and file-map
convention: [docs/conventions.md](docs/conventions.md).
