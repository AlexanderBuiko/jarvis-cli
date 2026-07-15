# RAG & retrieval

## Why do my RAG answers always say "I don't know"?

In strict mode (`rag_strict on`) the assistant declines when nothing relevant is
retrieved. If *every* answer is "I don't know", retrieval is returning nothing
useful. The usual causes:

- **`rag_index` is not set** — turn on RAG *and* name an index: `config set rag on`
  then `config set rag_index <name>` (see `index list`).
- **Question/index mismatch** — a hit-rate of 0% almost always means you're querying
  an index built from unrelated documents. Point `rag_index` at the right one.
- **Embedding-model mismatch** — see the dimension-mismatch entry below.

To sanity-check retrieval alone, run `index search <your question> name=<index>`; if
that returns nothing sensible, the answer will too.

## "Query vector dim X != index dim Y"

An index records the embedding provider/model it was built with, and the query must
be embedded the same way. This error means they differ — e.g. the index was built
with a local Ollama model but you're now querying with a cloud model (or vice
versa). Fix by either rebuilding the index with your current embedder, or setting
`JARVIS_EMBED_PROVIDER` / `JARVIS_EMBED_MODEL` to match the index's header (shown in
`index show <name>`).

## How do I make grounded answers cite their sources?

Citations are on by default (`rag_cite on`). Grounded answers append a `Sources` +
`Quotes` block, and cite inline as `filename › section`. If you don't see sources,
the turn probably wasn't grounded (weak or no context) — check the per-turn RAG notice.

## Retrieval finds too much / too little

Tune the second stage: `rag_k` (how many candidates), `rag_min_score` (drop weak
matches), `rag_top_n` (keep the best N), and `rag_rerank cross_encoder` for a more
accurate reorder. `rag ask <question>` shows retrieved-vs-kept side by side.
