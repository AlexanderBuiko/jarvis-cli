# Jarvis CLI — MCP Subsystem

Jarvis is an MCP **client**: it connects to one or more MCP servers, aggregates
their tools, and offers those tools to the model on every chat answer and task
stage. The code lives in `jarvis/mcp/`.

## Configuration (`config.py`)

A server is described declaratively by an `MCPServerConfig`: a `name` (also the
namespace prefix for its tools) and a `transport`:

- `stdio` — launch the server as a local subprocess (command + args + env).
- `streamable-http` / `sse` — connect to an already-running network server by URL,
  optionally sending an API key from `api_key_env` as the `X-API-Key` header.

The active fleet is resolved at call time by `default_servers()`:

1. A `servers.json` fleet file — searched at `$JARVIS_SERVERS_FILE`, then
   `./servers.json`, then `~/.jarvis/servers.json`. It can wire any number of
   network and stdio servers as data; `${VAR}` in any string is expanded from the
   environment so secrets stay out of the file.
2. Otherwise the single-server env wiring: `JARVIS_MCP_URL` (or legacy
   `JARVIS_TIME_MCP_URL`) → one streamable-http server named `jarvis`.
3. Otherwise no servers (no MCP tools).

## Registry (`registry.py`)

`MCPRegistry` owns the fleet: it connects every configured server (tolerating
partial failure — a dead server is recorded in `failures` and skipped), merges each
server's tools into one catalogue, and namespaces every tool as `<server>.<tool>`
(e.g. `weather.get_weather`). A bare tool name is accepted only when it is
unambiguous across the fleet. `call_tool` strips the prefix and routes to the owning
client. It is an async context manager.

## Provider (`provider.py`)

`MCPToolProvider` is a long-lived, **synchronous** facade over the async fleet. The
rest of Jarvis is synchronous while the MCP SDK is async and requires its
stdio/session contexts to be entered and exited in the same task; the provider
satisfies both by running one background thread whose event loop holds a single
long-lived service coroutine. Sync callers use three methods:

- `tool_specs()` — the function-calling tool schema attached to an LLM request.
- `call_tool(name, args)` — run a tool, get its text result (blocking).
- `close()` — stop the fleet (also registered at exit).

Tool calls are bounded by `JARVIS_MCP_CALL_TIMEOUT_S` (default 60s) so a wedged
server can't block a turn forever.

## Inspecting tools

`mcp list` shows the connected servers and every aggregated tool; `mcp call <tool>
[k=v …]` invokes one directly. These run against the agent's already-connected
provider when there is one, else open a throwaway connection as a connectivity
check. The agent calls the same tools automatically each turn.

## Local vs remote tools

Network servers (streamable-http) have a lifecycle independent of the CLI: start
them separately, and if one is down it simply contributes no tools. Local stdio
servers are launched as subprocesses by the client. A tool that must read local
machine state (for example, the current git branch of the developer's working tree)
belongs in a **local stdio** server, because a remote process cannot see the local
filesystem.

## Bundled local servers

Two local stdio servers ship with the CLI (wire them in `servers.json`; see
`servers.json.example`):

- **`git`** (`jarvis/mcp_servers/git_server.py`) — `get_current_branch`, reading the
  working tree at `GIT_REPO_PATH` (else the CLI's cwd).
- **`files`** (`jarvis/mcp_servers/files_server.py`) — lets the assistant work with
  project files under a root (`JARVIS_FILES_ROOT`, else cwd; paths that escape the root
  are refused, and VCS/cache/dep dirs and binary files are skipped):
  - `list_files(glob, limit)` — discover files.
  - `read_file(path, max_bytes)` — read text content.
  - `search_files(query, glob, regex, limit)` — `path:line: text` matches across many
    files (the "find every use of X" primitive).
  - `write_file(path, content, dry_run)` — create/modify a file, returning a unified
    diff. `dry_run=True` returns the diff **without writing** (a safe preview /
    change-list); a real write is gated (below).
  - `delete_file(path, dry_run)` — remove a file, returning the removal diff (refuses
    directories). `dry_run=True` previews without deleting; a real delete is gated like a
    write and is **journaled**, so `revert_file` restores the file's exact prior content.
  - `list_changes()` / `revert_file(path, force)` / `revert_last(force)` — the session
    **undo**. Every real write snapshots the file's prior state in an in-process journal,
    so a revert restores exactly what the assistant changed (a created file is deleted, a
    modified file is restored to its prior text) — precisely, without git's "revert to the
    last commit" imprecision. LIFO per file; if you've hand-edited a file since, revert is
    refused unless `force=True`.

Given a goal ("find every use of `build_rag_block`", "write an ADR describing X",
"ensure every module here has a docstring and fix any that don't"), the agent's
tool-calling loop picks these tools itself — it initiates the file work rather than
being told which file to open.

## File-write permission gate

A real `files.write_file` or `files.delete_file` (not a `dry_run` preview) passes through
a permission gate (`jarvis/mcp/permissions.py`, `ToolPermissions`) before it runs.
Read-only tools and dry-run previews are never gated. Standing authorisation is a config
toggle:

- `config set file_writes ask` (default) — the write isn't performed during the turn;
  it's **queued**. After the turn (spinner stopped, on the main thread) the REPL shows
  each queued change in a **bordered box** coloured by the action (green create / yellow
  update / red delete), with the first ~10 changed lines and the rest behind a "… N more"
  line; **Ctrl+S** (or `e`) expands/collapses it (only the live box toggles). Keys:
  **[Enter] apply once / [a] allow all this session / [s] skip**
  (`_process_pending_writes` in `jarvis/repl/loop.py`, box in `InputController.approve_write`
  / `frame_rows`). After deciding, the box **stays in the chat** footered with the choice
  (`→ applied` / `→ skipped`); the file isn't dumped twice. Approving applies the change
  (revertible via the journal); "allow all" grants the tool for the session.
- `config set file_writes auto` — writes apply immediately in-turn and return the diff.

Approval happens *after* the turn on purpose: the turn runs on a spinner worker thread
that can't own the terminal to prompt, so the gate queues the write and the REPL prompts
with the same `controller.select` menu the task pipeline uses for its gates. A skipped
write isn't an error — the model is told it's pending and moves on. The gate is CLI-side
only, so the server-side gateways (`/help`, `/review`, `/support`) are unaffected.
