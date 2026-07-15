# Jarvis CLI — Project Documentation

This `docs/` folder is the project knowledge base: a coherent description of the
**current state** of the jarvis-cli application. It is the corpus indexed for the
RAG-grounded `/help` assistant, so it is written as well-sectioned Markdown (the
structure-aware chunker splits on headings).

## Contents

- [overview.md](overview.md) — what Jarvis is, quick start, input modes, where state lives.
- [architecture.md](architecture.md) — design stance, layered structure, module map, request flow.
- [commands.md](commands.md) — the full REPL command surface.
- [configuration.md](configuration.md) — runtime parameters and environment variables.
- [subsystems-rag-indexing.md](subsystems-rag-indexing.md) — indexing pipeline and RAG generation.
- [subsystems-mcp.md](subsystems-mcp.md) — the MCP client subsystem (config, registry, provider).
- [subsystems-llm-providers.md](subsystems-llm-providers.md) — LLM engine, gateway, router, cloud/local.
- [tasks-and-memory.md](tasks-and-memory.md) — task pipeline, context strategies, memory, invariants, profile.

## Scope

These docs describe jarvis-cli itself. They are authored (not auto-generated) and
should be kept current as the code evolves; the index is rebuilt from them on demand
rather than on every change.
