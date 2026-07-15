# Jarvis CLI — Overview

## What Jarvis is

Jarvis is an interactive command-line AI assistant. It holds multi-turn
conversations through a pluggable LLM backend (OpenRouter in the cloud by default,
or a local Ollama model), and layers a number of "stateful agent" capabilities on
top: persistent conversation threads, a code-enforced task pipeline, retrieval-
augmented generation (RAG) over local document indexes, Model Context Protocol
(MCP) tools, a per-user profile, and global invariants (hard rules).

It runs as a REPL: you type prompts (sent to the model) or commands (handled by the
CLI). It is distributed as a Python package (`jarvis-cli`) exposing a `jarvis`
console entry point.

## Quick start

```bash
pip3 install -r requirements.txt      # or: pip3 install -e .
export OPENROUTER_API_KEY=your_key    # cloud engine; not needed if fully local
jarvis                                # or: python3 -m jarvis
```

Configuration can also be supplied via a `.env` file, loaded automatically at
startup — either project-local `./.env` or global `~/.jarvis/.env`. See
[configuration](configuration.md).

## The two input modes

The REPL has two modes, toggled by typing `!` on an empty line:

- **Prompt mode (`>`)** — input is sent to the agent as a chat message.
- **Command mode (`!`)** — input is dispatched to the REPL command handlers
  (`config`, `thread`, `task`, `index`, `rag`, `mcp`, `help`, …).

Line editing is provided by `prompt-toolkit`: `Ctrl+G` clears the buffer, the
arrow keys navigate history (or autocomplete suggestions when visible), and `Tab`
accepts a suggestion.

## Where state lives

Jarvis persists everything as inspectable JSON/Markdown under `~/.jarvis/`:
conversation threads, tasks, the profile, invariants, and document indexes. This
mirrors the project's philosophy — plain, greppable files, no database dependency
for the core experience. The index directory is overridable via `JARVIS_INDEX_DIR`.

## Two ways to use the model backend

The main chat turn is served by a provider chosen at runtime:

- **`openrouter`** — cloud, via your `OPENROUTER_API_KEY` (default).
- **`ollama`** — local, free, private (`config set provider ollama`).

Individual internal roles (utility calls, pipeline subagents) can be pinned to a
different provider than the main turn. See [LLM & providers](subsystems-llm-providers.md).
