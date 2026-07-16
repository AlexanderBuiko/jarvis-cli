# Jarvis CLI — Configuration

Configuration comes from two places: runtime **parameters** (changed with `config
set`, persisted per install) and **environment variables** (loaded from the real
environment, then `./.env`, then `~/.jarvis/.env`).

## Runtime parameters

### Sampling / model

- `model` (str) — OpenRouter model identifier. Changeable only on an empty thread.
- `temperature` (float, 0.0–2.0) — sampling temperature.
- `top_p` (float, 0.0–1.0) — nucleus sampling.
- `top_k` (int) — top-k cutoff.
- `max_tokens` (int) — maximum response tokens.
- `seed` (int | none) — random seed for reproducibility.

### Strategies

- `solution_strategy` — `direct` (default) | `step_by_step` | `prompt_generation`
  | `expert_panel`. How a single answer is produced (immediate, explicit reasoning,
  a two-stage optimised-prompt pipeline, or a three-expert panel with synthesis).
- `context_strategy` — `none` (default) | `compression` | `sliding_window` |
  `sticky_facts` | `dialogue_state` | `topics`. How the conversation context is
  managed across turns. Changeable only on an empty thread.
- `window_size` (int) — turns kept when `context_strategy=sliding_window` (default 10).

### Pipeline agents

- `review_agents` (int, 1–5) — reviewers on the validation swarm. 1 = single
  validator; >1 runs an independent reviewer panel + consolidator.
- `execution_agents` (int, 1–8) — agents executing the plan in parallel. 1 =
  sequential; >1 runs independent steps concurrently via `[after: …]` plan
  annotations.

### RAG (chat grounding)

- `rag` (bool) — ground chat answers in a local index (default off).
- `rag_index` (str) — name of the index to retrieve from.
- `rag_k` (int, 1–20, default 5) — candidates retrieved per message (top-K).
- `rag_min_score` (float, default 0) — relevance cutoff (drop chunks below this cosine).
- `rag_top_n` (int) — chunks kept after filter/rerank (top-N).
- `rag_rerank` — `off` | `cross_encoder` (local sentence-transformers reorder).
- `rag_rewrite` (bool) — rewrite the question into a better search query first.
- `rag_cite` (bool, default **off**) — debug view: append the Sources + verbatim
  Quotes for the chunks used. Off by default (clean prose, inline `[n]` stripped);
  `config set rag_cite on` turns the citation block on.
- `rag_strict` (bool, default off) — closed-domain mode: weak/irrelevant context →
  "I don't know" instead of answering from general knowledge.
- `rag_idk_threshold` (float, default 0) — confidence bar below which context is "weak".

## Environment variables

- `OPENROUTER_API_KEY` — required for the cloud engine.
- `JARVIS_LLM_PROVIDER` — main-turn engine: `openrouter` (default) or `ollama`.
- `JARVIS_UTILITY_PROVIDER` / `JARVIS_SUBAGENT_PROVIDER` — per-role provider pins.
- `JARVIS_OLLAMA_MODEL` — local chat model (e.g. `qwen2.5:7b`).
- `JARVIS_OLLAMA_URL` — local Ollama daemon URL (default `http://localhost:11434`).
- `JARVIS_EMBED_PROVIDER` — embedding provider for indexing: `ollama` (default),
  `openrouter`, or `fake`.
- `JARVIS_EMBED_MODEL` — embedding model (defaults per provider).
- `JARVIS_INDEX_DIR` — where indexes are read/written (default `~/.jarvis/indexes`).
  Both the CLI and the remote `/help` server resolve this, so point them at the
  same place (a shared dir locally, a mounted bucket in the cloud).
- `JARVIS_MCP_URL` — URL of the standalone Jarvis MCP server (legacy:
  `JARVIS_TIME_MCP_URL`).
- `MCP_API_KEY` — API key sent as `X-API-Key` to the network MCP server once auth is on.
- `JARVIS_SERVERS_FILE` — path to a `servers.json` fleet file (takes precedence over
  the single `JARVIS_MCP_URL`).
