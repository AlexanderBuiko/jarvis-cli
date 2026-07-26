# Week 4 — MCP (Model Context Protocol)

**Source:** `transcriptions/04-mcp-summary.md`,
`transcriptions/04-mcp-notes.md` (+ raw `04_4_неделя_6_поток_v1.md`)
**Theme:** Connect AI apps to external tools and data through one open protocol.

## What MCP is

**MCP** is an open standard linking AI apps to external tools/data. An LLM does
not know the live state of corporate systems, trackers, repos, calendars, files,
or CI/CD. MCP adds a shared layer: a **host** (with the LLM) uses an **MCP
client**; a **server** publishes available **tools**; a handler turns a tool call
into a concrete API request, CLI command, or internal function call.

MCP is **not** a framework and does **not** replace APIs. SDKs (Kotlin, Python,
TS) just implement the protocol. The API stays the backend interface; the MCP
server adapts it for AI hosts. One integration then serves several compatible
clients — no separate wiring per model–service pair.

## Key points

- Most useful for corporate systems, knowledge bases, repos, DevOps, calendars,
  mail, and complex apps (CRM, 1C, SAP).
- A **tool** is one named operation with a description and input schema. A server
  can expose a safe subset (e.g. read without write).
- **JSON-RPC 2.0** defines the message shape. **stdio** transport = local
  subprocess; **remote** transport = network server. Message format and delivery
  are separate layers.
- A remote MCP server needs hosting, protocol impl, backend access,
  authentication, TLS, publication, and host connection.

## Security

Security is not "has a schema". External text can carry **prompt injection**; a
careless handler can pass a malicious value into a shell or a critical API.
Practical defences: least privilege, read-only mode, strict validation,
allowlists, sandbox, timeouts, audit log, separate credentials, and confirmation
of destructive actions. Natural language does not cancel business rules — the
agent must obey the same access limits as a normal client.

## Token cost

Cost appears mainly in **sampling calls** to the LLM. The prompt carries system
instructions, user input, history, tool schemas, and prior tool results. Sources
of overhead: **idle** (schemas present though tools unused), **batching** (many
actions → repeated calls + growing history), **schema weight** (many detailed
tools enlarge input). There is no universal quadratic law — it depends on host,
caching, compaction, model, and prompt assembly.

## MCP vs Skill + CLI

- **MCP wins** for: remote servers, public tools, several AI hosts, centralised
  credentials, formal schemas.
- **Skill + CLI wins** for: a local environment where a utility is already
  installed, instructions load on demand, several ops can batch, idle overhead is
  zero.

"MCP deprecated" does not mean the tech is cancelled — it means for some local /
CLI tasks MCP can be costlier and more complex. Choose by topology, security
model, reuse, and measured token flow. Start with one narrow **read-only** use
case; define owner, scope, validation, error model, and logging per tool; then
measure value (latency, success rate, token cost, blocked dangerous requests).

## Maps to jarvis-cli

- Client side: `jarvis/mcp/` (registry, provider, permissions gate).
- Server side: `jarvis/mcp_servers/` (`git_server.py`, `files_server.py`).
- Remote deploy: the standalone `jarvis-mcp-server` (Streamable HTTP, X-API-Key
  auth, Cloud Run) — see `jarvis-mcp-server-deploy` memory.
- Rule (antipattern 4): an MCP tool must not raise — degrade to
  `f"error: {exc}"`; mutating tools take `dry_run: bool = False` and return the
  diff without touching disk.

## Week's assignment

Learn the host/client/server architecture; connect existing public tools;
implement an MCP server over an external API; orchestrate several tools in your
own agent; use MCP in a real task; compare MCP vs Skill + CLI on cost and
convenience (same task both ways, record schemas, sampling calls, tool results,
final prompt tokens).
