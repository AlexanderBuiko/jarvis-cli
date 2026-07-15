# Jarvis CLI — Architecture

## Design stance

Jarvis is built from small, interface-driven components wired together at the
edges: abstractions in the middle, concrete providers at the boundary. The same
pattern recurs across subsystems — an `LLMEngine` protocol with cloud/local/fake
implementations, an `Embedder` protocol with Ollama/OpenRouter/Fake implementations,
and a `ProfileStore`/`TaskStore`/thread store family over plain files. Hard rules
(task-stage transitions, invariants) are enforced in **code**, not prompt text.

## Layered structure

- **REPL layer** (`jarvis/repl/`) — the interactive loop, input handling, command
  dispatch, and the live task/tool trace rendering.
- **Agent layer** (`jarvis/agent.py`) — historically a single `JarvisAgent` facade;
  refactored to delegate to focused collaborators (see below).
- **Service collaborators** — `jarvis/llm/` (gateway + router + engine),
  `jarvis/conversation/`, `jarvis/memory/`, `jarvis/personalization/`,
  `jarvis/prompt_builder/`.
- **Task pipeline** (`jarvis/pipeline/`) — the orchestrator, finite-state machine,
  per-stage agents, invariant checker, validation swarm, and parallel execution.
- **Retrieval** (`jarvis/indexing/` + `jarvis/rag/`) — document indexing and the
  RAG generation/evaluation layer.
- **Tools** (`jarvis/mcp/`) — the MCP client fleet that surfaces external tools to
  the agent each turn.
- **Persistence** (`jarvis/session/`) — thread, task, profile, invariant, and
  behaviour-log stores, plus the session/API accounting store.

## Module map

| Path | Responsibility |
|---|---|
| `jarvis/repl/loop.py` | REPL loop; command dispatch (`_dispatch`); task drive loop |
| `jarvis/repl/commands.py` | Command handlers + the static `HELP_TEXT` |
| `jarvis/agent.py` | `JarvisAgent` facade; answering, RAG, thread/task ops |
| `jarvis/llm/gateway.py` | `LLMGateway` — the single call site for model requests + tool use |
| `jarvis/llm/router.py` | Provider routing (`make_engine`, current provider) |
| `jarvis/llm/engine.py` | `LLMEngine` protocol (provider-agnostic) |
| `jarvis/prompt_builder/builder.py` | System-prompt assembly; `build_rag_block` |
| `jarvis/indexing/` | Loader, chunkers, embedders, JSON store, build/search pipeline |
| `jarvis/rag/` | Grounded answering, citations, enhancement (filter/rerank/rewrite), evaluation |
| `jarvis/mcp/` | MCP config, client, registry, sync provider, CLI |
| `jarvis/pipeline/` | Orchestrator, FSM, stages, runner, invariants, swarm, parallel |
| `jarvis/session/` | Thread/task/profile/invariant/behaviour stores; session accounting |
| `jarvis/conversation/` | Conversation service + dialogue state |
| `jarvis/memory/` | Memory coordinator (STM/WM/LTM) |
| `jarvis/personalization/` | Profile personalisation service |

## The refactor lineage

`JarvisAgent` was once an ~800-line "god object". It was dissolved into an
`LLMGateway` (model calls + tool use), a `MemoryCoordinator`, a
`ConversationService`, a `PersonalizationService`, and a `StageRunner` seam that the
task pipeline plugs into. The agent remains as a thin facade over these. This seam
work is what lets the RAG and MCP primitives be reused outside the CLI (for example,
by a remote server that answers project questions).

## Request flow (chat turn)

1. Read user input (prompt mode).
2. Load profile + invariants; select the relevant context layers for the active
   thread's context strategy.
3. If RAG is enabled, retrieve chunks and inject a grounded context block.
4. `PromptBuilder` assembles the system prompt.
5. `LLMGateway` sends the request — offering MCP tools — and handles any tool calls.
6. The invariant checker screens the response; on a hard-rule conflict the agent
   refuses, names the invariant, and explains why.
7. The turn is persisted (tokens/cost accounted) and the answer is returned.
