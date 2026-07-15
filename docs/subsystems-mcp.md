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
