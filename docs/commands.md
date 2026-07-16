# Jarvis CLI — Command Surface

Commands are entered in command mode (toggle with `!`). This is the current command
surface as dispatched in `jarvis/repl/loop.py`.

## General

- `help` — show the static help and parameter reference.
- `exit` / `quit` — leave Jarvis.

## Configuration

- `config show` — show active configuration parameters.
- `config set <key> <value>` — set one parameter.
- `config update <k=v> …` — set several at once.
- `config reset` — clear all parameters (revert to API defaults).

## Threads (conversation)

- `thread` — show the current conversation context.
- `thread clear` — clear the active thread's messages.
- `thread load` / `thread load <name-or-id>` — list threads / switch to one.
- `thread new [name]` — start a new empty thread.
- `thread rename <name>` — rename the active thread.
- `thread delete <name-or-id>` — delete a thread.
- `thread summary` — tokens, cost, compression state, facts, topic summaries (with charts).
- `thread state` — the dialogue task state (Goal / Given / Constraints).

## Session

- `session chat` — full conversation transcript.
- `session summary` — aggregate statistics with cost charts.
- `session api` — raw API request/response payloads.

## MCP tools

- `mcp list` — list the aggregated MCP tools offered to the agent each turn.
- `mcp call <tool> [k=v …]` — invoke a tool directly (e.g. `mcp call weather.get_weather city=London`).

MCP tools are offered to the model automatically on every chat answer and task
stage; `mcp` is for inspecting/calling them by hand.

The bundled local **`files`** server lets the assistant read, search across many
files, and create / modify / delete project files under `JARVIS_FILES_ROOT` (default:
cwd) — give it a goal ("find every use of X", "write an ADR", "delete the stale notes file")
and its tool loop does the file work itself. Every write is journaled, so you can undo it
in the same session — ask the assistant to "revert that", or call
`mcp call files.revert_last` / `files.revert_file path=…` (see `files.list_changes`).
Creating/modifying a file is gated by the `file_writes` config toggle:

- `config set file_writes ask` (default) — after the turn, each proposed write is shown
  as a diff and you choose apply once / apply and allow all this session / skip.
- `config set file_writes auto` — apply writes immediately and return the diff.

## Document indexing (RAG substrate)

- `index build <path> [k=v …]` — load → chunk → embed → store an index.
- `index list` — list saved indexes.
- `index show [name]` — an index's header and sample chunks.
- `index search <query> [k=v]` — semantic search over an index.
- `index compare <path> [k=v]` — compare fixed vs structure-aware chunking.
- `index delete <name>` — delete an index.

## RAG comparison & evaluation

- `rag ask <question> [k=v]` — answer once without RAG vs with RAG, side by side.
- `rag eval [name=..] [k=v]` — run the control questions and score quality.
- `rag compare [k=v]` — local vs cloud quality/speed/stability.
- `rag bench [k=v]` — optimization matrix (base vs optimized, + resources).

## Tasks (working memory)

- `task` / `task show` — show the active task.
- `task new [name]` — create a task workspace and enter it.
- `task list` — list saved tasks and their stages.
- `task start <name-or-id>` — enter an existing task.
- `task run` — continue the entered task with no new input.
- `task exit` — leave the task (state preserved).
- `task delete <name-or-id>` — delete a task.
- `task attach` / `task detach <name-or-id>` — pin/unpin a finished task's result into the thread.

Tasks and chat are separate surfaces. Inside a task your messages drive its
pipeline (clarification → planning → execution → validation → done); outside, they
are normal chat.

## Invariants & profile

- `invariants` / `invariants init` — show / scaffold the global hard-rule file.
- `profile` / `profile onboard` — show / (re)run the onboarding interview.
- `personalize` — propose a `profile.md` Style update from recent activity (confirm before applying).

## Quiz

- `quiz build [k=v]` — generate an MCQ pool from an index.
- `quiz upload [file=.. url=..]` — upload a reviewed pool to the server.
