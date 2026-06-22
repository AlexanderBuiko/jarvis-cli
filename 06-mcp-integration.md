# MCP Integration — Research, Prototype & Architecture

A maintainable, extensible Model Context Protocol (MCP) layer for Jarvis. Built on
the **official MCP Python SDK**, runs **entirely locally** (stdio subprocesses, no
cloud), and plugs into the existing `LLMEngine`/`LLMGateway` abstractions.

Code lives in [`jarvis/mcp/`](jarvis/mcp). Tests: [`tests/test_mcp.py`](tests/test_mcp.py).

---

## Phase 1 — Research & Feasibility

### 1. Recommended way to build an MCP client in Python today

Use the **official MCP Python SDK**, package [`mcp`](https://pypi.org/project/mcp/)
(installed here: **1.28.0**; we pin `mcp>=1.8`). Requires Python ≥ 3.12 (we run 3.12.6).

- **Client side**: `mcp.client.stdio.stdio_client(params)` launches a server as a
  subprocess and yields a `(read, write)` stream pair; `mcp.ClientSession(read, write)`
  wraps those into a session. After `await session.initialize()` you get
  `list_tools()`, `call_tool()`, `list_resources()`, `list_prompts()`.
- **Server side**: `mcp.server.fastmcp.FastMCP` — decorate plain functions with
  `@mcp.tool()`; `mcp.run()` serves over stdio by default.
- The API is **async** (anyio/asyncio). The wire format is JSON-RPC 2.0.
- v1.x is the recommended/stable line (v2 is in alpha as of mid-2026).

> Repo: <https://github.com/modelcontextprotocol/python-sdk> ·
> Docs: <https://modelcontextprotocol.io/docs/sdk>

### 2. Existing public MCP servers

- **Weather (priority)** — no first-party reference weather server, but several
  community ones exist: [`isdaniel/mcp_weather_server`](https://github.com/isdaniel/mcp_weather_server)
  (Open-Meteo, key-less), [`TimLukaHorstmann/mcp-weather`](https://github.com/TimLukaHorstmann/mcp-weather)
  (AccuWeather, needs key), [`weather-mcp/weather-mcp`](https://github.com/weather-mcp/weather-mcp) (NOAA + Open-Meteo).
- **Filesystem (secondary)** — official reference
  [`modelcontextprotocol/servers/src/filesystem`](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) (Node).
- **Git/GitHub (comparison)** — official reference `git` server; GitHub provides its own.
- Other official references: `fetch`, `memory`, `everything` (a test server).

> Index: <https://github.com/modelcontextprotocol/servers>

### 3. What MCP supports

- **Local custom servers** — **yes.** That's the primary model: a server is just a
  process speaking MCP over stdio. `FastMCP` makes one in ~10 lines.
- **Multiple simultaneous servers** — **yes.** A client (host) opens an independent
  session per server; nothing is shared between them.
- **Tool aggregation across servers** — **not built in.** The protocol is per-server;
  aggregation is the *host's* job. Our `MCPRegistry` provides it (see Phase 5).

### 4. Minimal architecture for a CLI-based MCP client

```
config (how to launch each server)
   → MCPClient (one async stdio session: connect / list_tools / call_tool / aclose)
      → MCPRegistry (many clients: connect-all, aggregate, namespace, route)
         → cli (sync `list` / `call` front-end)         ← Phase 2 PoC
         → bridge (MCP tools → LLM function-call schema) ← future agent execution
```

### Recommended stack

| Concern | Choice |
|---|---|
| SDK | official `mcp` (`>=1.8`; 1.28.0 here) |
| Transport | **stdio** subprocess (local, no ports/cloud) |
| Server | `FastMCP` |
| Weather data | Open-Meteo (free, **no API key**) + mock fallback |
| TLS on macOS | `certifi` CA bundle (already a transitive dep) |

---

## Phases 2–4 — What was built

A single `jarvis.mcp` package, each file one responsibility:

| File | Role |
|---|---|
| [`config.py`](jarvis/mcp/config.py) | `MCPServerConfig` dataclass + `DEFAULT_SERVERS` fleet |
| [`client.py`](jarvis/mcp/client.py) | `MCPClient` — one async server connection |
| [`registry.py`](jarvis/mcp/registry.py) | `MCPRegistry` — multi-server aggregation + routing |
| [`bridge.py`](jarvis/mcp/bridge.py) | MCP tool → OpenRouter function-call schema |
| [`servers/weather.py`](jarvis/mcp/servers/weather.py) | local `FastMCP` server: `get_weather`, `echo` |
| [`cli.py`](jarvis/mcp/cli.py) | `python -m jarvis.mcp` proof-of-concept |

**Phase 3 decision — local server over public.** A local server we own needs no API
key, no network dependency, and a contract we control — better for a reproducible
PoC and offline tests. `get_weather` calls the key-less Open-Meteo API and **falls
back to deterministic mock data** when offline, so it never hard-fails.

### Verified CLI output

```
$ python -m jarvis.mcp list
✓ Connected: weather

Tools (2):
  • weather.get_weather      Return current weather for a city as a short human-readable line.
  • weather.echo             Return the input unchanged — a connectivity smoke-test tool.

$ python -m jarvis.mcp call weather.get_weather city=London
London, United Kingdom: 24.9°C, mainly clear (source: Open-Meteo)   # offline → "(mock)"

$ python -m jarvis.mcp call echo text="hello mcp"
hello mcp
```

`tests/test_mcp.py` drives this same stdio path (8 tests; full suite 100 passing).

### One gotcha worth recording

The MCP SDK's `stdio_client`/`ClientSession` use anyio cancel scopes that **must be
entered and exited in the same task**. Connecting a client *and* re-entering it as a
context manager runs `connect()` twice and leaks the first scope, producing
`RuntimeError: Attempted to exit cancel scope in a different task`. Fix: connect
once, register teardown with `AsyncExitStack.push_async_callback(client.aclose)` so
everything lives and dies in one task. (See the comment in `registry.connect`.)

---

## Phase 5 — Architecture for Extensibility

### Connecting to multiple servers
Adding a server is a **data change** in `DEFAULT_SERVERS`, not a code change:

```python
DEFAULT_SERVERS = [
    MCPServerConfig(name="weather", args=["-m", "jarvis.mcp.servers.weather"]),
    MCPServerConfig(name="fs", command="npx",
                    args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]),
]
```

`MCPRegistry.connect()` opens each in its own `MCPClient` and tolerates **partial
failure** — a server that won't start is recorded in `.failures` and skipped, the
rest stay up. The `MCPServerConfig` dataclass extends to HTTP/SSE transports later
by adding a `transport` field the registry branches on.

### Tool discovery aggregation
`MCPRegistry.list_tools()` fans out `list_tools()` across every connected client and
merges the results into one catalogue of `AggregatedTool(server, name, description,
input_schema)`. The host owns the merged view; servers stay ignorant of each other.

### Naming-collision handling
Every tool is exposed as **`<server>.<tool>`** (e.g. `weather.get_weather`). Because
the prefix is the server name — unique by construction — two servers can both expose
`search` with no clash. The **bare name** is accepted as a convenience alias *only
when unambiguous*; if two servers share it, `call_tool("search")` raises with the
qualified alternatives. (Tested in `CollisionAndBridgeTest`.)

> **Wire-name caveat.** Function-calling APIs (OpenAI/Anthropic) require tool names
> to match `^[a-zA-Z0-9_-]{1,64}$`, so the dot in the qualified name is **rejected
> with a 400**. The bridge therefore emits a wire-safe name using `__` as the
> separator (`weather__get_weather`); the provider keeps a reverse map and accepts
> either form when routing. Dots stay the human/CLI convention; `__` is the wire
> convention. (See `bridge.to_wire_name` and `provider._wire_to_qualified`.)

### Deferred / future tool execution
`bridge.tools_to_openrouter()` converts the catalogue into the function-calling
`tools` array the existing LLM stack already speaks, using the **qualified name** as
the function name. The intended flow, plugging into the seam the stage agents were
designed for (`pipeline/base.py` — "(later) tools"):

1. Orchestrator asks the registry for its catalogue → `tools_to_openrouter()`.
2. Passes `tools=…` to a model call via the existing `LLMGateway` (the single
   chokepoint — accounting/retries stay in one place).
3. On a tool call, route the qualified name straight back through
   `MCPRegistry.call_tool(name, args)` — no lookup table needed, the name *is* the route.

This keeps the registry provider-agnostic and the agent MCP-agnostic: the only
coupling is this one ~30-line bridge module.

### Tool-use loop & the invariant checker (gotchas)
Wiring tools into the per-turn loop surfaced three issues worth recording:

- **Faithful call records.** The gateway appends the tool exchange to the caller's
  message list, but passes a **snapshot** (`list(messages)`) to each API call — so
  `session api` shows each request frozen at send time, not mutated by later rounds.
- **The checker must see tool context.** The invariant checker is a separate LLM
  call that originally saw only the final reply. With tools, a real Open-Meteo
  reading ("Moscow 19°C") looked like an invented fact → it fired *No fabrication*
  and the resolution step rewrote the correct answer into a refusal. Fix: the
  checker now receives a **TOOL ACTIVITY** block (tool calls + results) and is told
  tool outputs are trusted sources, so grounded facts aren't flagged (faithful
  rounding/rephrasing is explicitly allowed; unsupported additions are still
  caught). The resolution step self-labels `CORRECTED:` vs `REFUSED:` so a routine
  self-correction shows a calm note rather than a "your request conflicted"
  warning. (See `invariants._tool_context`, `_interpret_resolution`, and
  `build_invariant_check_prompt`.)
- **Server log noise.** The stdio server's per-request INFO logging corrupted the
  CLI spinner; the weather server now runs at `log_level="WARNING"`.

### Design principles honoured
- **Simplicity over overengineering** — one connection class, one registry, one bridge.
- **Local only** — stdio subprocesses; no ports, no cloud.
- **Official SDK** — `mcp` for both client and server.
- **Build from abstractions** — mirrors the repo's `LLMEngine`/`LLMGateway` stance;
  the bridge targets the same function-call schema, so MCP tools become available to
  every stage agent through the gateway that already exists.
