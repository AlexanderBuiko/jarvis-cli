# Week 5 — RAG: Embeddings, Vector Search and Chunking

**Source:** `transcriptions/05-rag-raw.md`, `transcriptions/5_неделя_6_поток_v1.md`
**Theme:** Augment LLM answers with your own internal knowledge at inference time.

## What RAG is

**RAG (Retrieval Augmented Generation)** augments LLM answers with external
knowledge *during inference*. The answer comes not only from what the model
learned in training but also from the specific internal knowledge of your system.

Difference from MCP:

- **MCP** — talk to external sources (third-party APIs, tools, data).
- **RAG** — work with internal org knowledge (knowledge bases, docs, Confluence).

RAG happens **at inference time** — it is loading data into the model's context,
not a call to an external tool.

## Why you need it

Problems without RAG:

1. **Incomplete context** — models trained on general internet data, unrelated to
   your internal knowledge.
2. **Mixed data** — internal history mixes process versions, teams, stale and
   current docs; the model cannot separate them like a human.
3. **Hallucinations** — the model returns an "average" (generic code-review norms
   instead of *your* team's policy).
4. **False positives** — the most dangerous: not a wrong answer, but one that
   *looks* right.

Three additive (not exclusive) ways to improve an LLM: **prompt optimisation**
(MD files, skills, sub-agents), **RAG** (context optimisation via external
knowledge — vector DBs, embeddings), **fine-tuning** (change the weights).

## The RAG pipeline

1. User asks a question.
2. Model analyses the query and spots knowledge gaps.
3. Query hits a **vector database** of documents.
4. Semantically similar text **chunks** are found.
5. Chunks are **combined with the prompt**.
6. Model returns an answer **with a source reference**.

Good RAG answer: *"Per the code-review policy [Confluence link], minimum 2
approvals before merge, max review time 24h."*

## Embeddings

- **Generative models** (Claude, ChatGPT): text → text.
- **Embedding models** (e.g. `nomic-embed-text` via Ollama): text → **vector**
  (numbers) for finding semantically similar texts.
- A **vector** is an array of numbers representing text (e.g. 768 or 1024 dims).
- **Cosine similarity**: `1` = same meaning, `0` = unrelated, `-1` = opposite.
- More dimensions → fewer "collisions"; close meanings stay close in space.

Embedding pipeline: **tokenise** → **embedding layer** (vector per token) →
**self-attention** (relations between words) → **pooling** (average into one
sentence vector) → **compare** against stored vectors.

## Chunking

Text is cut into **chunks** before vectorising:

- **Fixed size** — cut every N tokens; simple, but may cut mid-sentence and lose
  context.
- **Semantic** — cut by meaning (paragraphs, sections); more accurate, harder.
- **Overlap** — chunks partly overlap so a boundary is never "open":

  ```
  no overlap:  [1-500] [501-1000] [1001-1500]
  overlap:     [1-500] [451-950]  [901-1400]
  ```

Chunk size and overlap % are found **experimentally**, per data and task.
Rule of thumb: chunk size **500–1000 tokens**.

## Maps to jarvis-cli

- Retrieval half: `jarvis/indexing/` — `Embedder` Protocol (Ollama default /
  OpenRouter / Fake), JSON vector store, fixed + structure chunkers, `index` CLI
  (see `project_indexing_pipeline` memory).
- Generation half: `jarvis/rag/` — retrieval-augmented generation, eval, optional
  rerank (`sentence-transformers` extra, never a hard import).
- Answers cite sources (RAG citations); reranking is opt-in.

## Week's assignment

Build the RAG loop: embed documents, store vectors, retrieve semantically similar
chunks by query, combine with the prompt, and return grounded answers with source
references. Tune chunk size / overlap experimentally.
