# Jarvis CLI — RAG & Indexing Subsystem

Retrieval is split into two packages: `jarvis/indexing/` builds and searches vector
indexes (the substrate), and `jarvis/rag/` uses an index to answer questions (the
generation and evaluation layer).

## Indexing pipeline

`jarvis/indexing/` implements load → chunk → embed → store:

- **Loader** (`loader.py`) — reads UTF-8 `.md`/`.markdown`/`.txt` from a file or
  (recursively) a directory. Binary/empty files are skipped. Each `Document` carries
  provenance (source path, filename, first-H1 title) used for citations.
- **Chunkers** (`chunking.py`) — two strategies registered in `CHUNKERS`:
  - `fixed` — fixed-size chunks with overlap.
  - `structure` — Markdown structure-aware, splitting on headings/sections. This is
    why documentation should be written with clear headings.
- **Embedders** (`embeddings.py`) — an `Embedder` protocol with `OllamaEmbedder`
  (default), `OpenRouterEmbedder`, and a deterministic `FakeEmbedder` for tests.
  `make_embedder(provider, model)` is the factory.
- **Store** (`store.py`) — `IndexStore` persists one JSON file per index under the
  directory from `default_index_dir()` (`JARVIS_INDEX_DIR`, else `~/.jarvis/indexes`).
  Embeddings are unit-normalised at write time, so cosine similarity is a plain dot
  product at query time (`cosine_top_k`). The header records provider/model/dim, so a
  query is always embedded the same way the index was built — and a dimension
  mismatch raises rather than silently comparing against an incompatible index.
- **Pipeline** (`pipeline.py`) — `IndexPipeline.build(...)` ties it together and
  returns a `BuildResult`; `IndexPipeline.search(name, query, k)` returns scored
  records with full metadata.

## RAG generation

`jarvis/rag/` and the agent's RAG methods turn retrieval into grounded answers:

- **Retrieve** — top-K chunks for a question, embedded with the index's own
  provider/model.
- **Enhance** (`rag/enhance.py`) — an optional second stage: a relevance filter
  (`apply_filter`), an optional cross-encoder rerank (`CrossEncoderReranker`, needs
  `sentence-transformers`), and an optional query rewrite (`rewrite_query`, one LLM
  call). `enhance_results` runs filter → rerank → top-N and never empties a
  non-empty input.
- **Ground & cite** — `build_rag_block` (in `prompt_builder/builder.py`) turns the
  kept chunks into a context block; `build_citations` (in `rag/cite.py`) appends
  mandatory Sources + verbatim Quotes; `idk_message` is the deterministic "I don't
  know" used in strict mode.
- **Decide** — the agent's `_rag_decide` chooses per turn: strong context → ground
  and cite; weak context under `rag_strict` → "I don't know"; weak context otherwise
  → answer from general knowledge (so off-topic chat isn't hijacked).

## Chat RAG mode

Once an index is built, ground a thread's answers in it:

```
config set rag on
config set rag_index <name>
```

Each prompt-mode message then retrieves the top chunks, injects them, and the answer
cites the source as `filename › section`. A per-turn notice shows which sources were
used. `rag ask` shows the with/without-RAG comparison side by side.

## Evaluation

`rag eval` runs a control-question set and scores retrieval hit-rate and answer
quality; `rag compare` and `rag bench` benchmark providers/configurations on
quality, speed, and stability. Per-index question sets live under
`knowledge_base/eval/<index>_questions.json`.
