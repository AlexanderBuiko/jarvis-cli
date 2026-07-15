# Jarvis CLI — LLM Engine & Providers

Model access is provider-agnostic. The chat turn, internal utility calls, and
pipeline subagents all go through one gateway over a swappable engine.

## The abstraction

- **`LLMEngine`** (`jarvis/llm/engine.py`) — the provider-agnostic protocol every
  backend implements.
- **`LLMGateway`** (`jarvis/llm/gateway.py`) — the single call site for model
  requests. It attaches the MCP tool schema, handles the model's tool calls, and
  records token/cost accounting. Everything that talks to the model does so through
  the gateway.
- **Router** (`jarvis/llm/router.py`) — `make_engine(provider)` builds the concrete
  engine; `current_provider(config)` resolves which provider a role should use.

## Providers

- **`openrouter`** (`jarvis/openrouter/client.py`) — the cloud engine, using
  `OPENROUTER_API_KEY`. Default main-turn provider.
- **`ollama`** (`jarvis/ollama/client.py`) — a local daemon (`JARVIS_OLLAMA_URL`,
  default `http://localhost:11434`) serving a local model such as `qwen2.5:7b`.
  Free and private. The client also sends `X-API-Key` so it can reach an
  authenticated local LLM service if one is configured.

## Live cloud ↔ local switching

The main turn's provider is a live toggle: `config set provider ollama` (or
`openrouter`) switches it without restarting. The default is read from
`JARVIS_LLM_PROVIDER`.

## Per-role provider pins

Internal roles can be pinned to a fixed engine independent of the main toggle,
which is useful for keeping the main answer on the cloud while running cheap
internal calls locally (or vice versa):

- `JARVIS_UTILITY_PROVIDER` — invariant checks, memory, personalisation.
- `JARVIS_SUBAGENT_PROVIDER` — pipeline stage agents (planning / execution / validation).

When unset, a role follows the main provider toggle.

## Embeddings

Embeddings are a separate provider axis from chat: `JARVIS_EMBED_PROVIDER`
(`ollama` default / `openrouter` / `fake`) and `JARVIS_EMBED_MODEL`. An index
records the embedding provider/model it was built with so queries are always
embedded the same way. When retrieval must run somewhere without a local Ollama
(for example a cloud server or CI), build the index with cloud embeddings so both
sides match.

## Accounting

Token usage and cost are tracked per request and aggregated per thread/task/session
(`jarvis/llm/accounting.py` and the session store). `session summary` and `thread
summary` render cost charts from this data.
