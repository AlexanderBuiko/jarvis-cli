# Connecting to the MCP server

## How do I point the CLI at the MCP server?

Set the server URL (and key, if the server enforces auth) in `~/.jarvis/.env`:

```
JARVIS_MCP_URL=https://your-service.run.app/mcp
MCP_API_KEY=<the server's key>
```

`mcp list` should then show the server and its tools, namespaced `jarvis.*`
(e.g. `jarvis.get_current_time`, `jarvis.get_ticket`). Call one by hand with
`mcp call jarvis.get_ticket ticket_id=T-1002`.

## "server unreachable" vs "unauthorized" — what's the difference?

- **Unreachable** → a URL/network problem. Check `JARVIS_MCP_URL` (it should end in
  `/mcp`) and that the server is up (`curl $URL/healthz`).
- **Unauthorized (401)** → a key problem. See the Authorization FAQ.

## Can I connect several servers at once?

Yes. Create a `servers.json` (see `servers.json.example`) listing multiple servers —
network (`streamable-http`) and local (`stdio`) — and Jarvis aggregates all their
tools, namespaced by server. This is how the local `git` tools and the remote
`jarvis` tools appear together.

## The tools don't show up

If `mcp list` shows a server under failures, read the reason it prints. Common cases:
a bad URL, a missing key, or (for stdio servers) a launch command that isn't
installed. A server that fails to connect is skipped — the rest still work.
