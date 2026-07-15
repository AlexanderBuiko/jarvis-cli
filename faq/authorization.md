# Authorization & API keys

## Why am I getting "401 Unauthorized" or "✗ jarvis: unauthorized"?

The MCP server requires an API key whenever `MCP_API_KEY` is set on the server
(which it is once you deploy publicly). Every request must carry that key in the
`X-API-Key` header. The CLI sends it automatically **only if** the same value is in
your environment.

Fix it by putting the server's key in `~/.jarvis/.env`:

```
MCP_API_KEY=<the value the server was deployed with>
```

If you deployed to Cloud Run, read the deployed key back from Secret Manager:

```
gcloud secrets versions access latest --secret=mcp-api-key
```

A wrong or missing key is exactly what produces `401` on `POST` and
`✗ jarvis: unauthorized` in `mcp list`.

## It worked locally but broke after deploying to Cloud Run

Local testing usually runs the server **without** auth, so no key is needed. As soon
as you set `MCP_API_KEY` on the deployed server, every request needs the matching
key. Update `~/.jarvis/.env` (and any CI secrets like `MCP_API_KEY`) with the
deployed value. Nothing about your code changed — only the auth requirement did.

## Which API keys does Jarvis need?

- `OPENROUTER_API_KEY` — the cloud LLM provider, used for cloud chat answers and
  cloud embeddings. Required unless you run fully local.
- `MCP_API_KEY` — sent as `X-API-Key` to reach an authenticated MCP server.

Keys live in `~/.jarvis/.env` (global) or `./.env` (project) and are loaded at
startup. Never commit a real `.env`.

## How do I check my key is being sent?

Run `mcp list`. A healthy connection prints the server and its tools; an auth
problem prints `✗ jarvis: unauthorized`. If the server is simply unreachable you'll
see a connection error instead — that's a URL problem (`JARVIS_MCP_URL`), not a key
problem.
