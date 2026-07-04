# RAG second stage — manual test cases (filter / rerank / rewrite)

How to verify, by hand, the second retrieval stage added after search:
a **relevance filter** (similarity cutoff + top‑N), an optional **cross‑encoder
reranker**, and **query rewriting** — plus the before/after quality comparison.

Pipeline being tested:

```
question → [rewrite?] → embed → search top-K → [filter / rerank → top-N] → LLM
```

> **Important:** filtering and reranking only *help* when the similarity scores
> are meaningful — i.e. with real embeddings (Ollama or OpenRouter). With the
> offline `fake` provider the scores are random, so a threshold prunes good and
> bad chunks alike. Use a real embedder for these tests.

---

## Prerequisites

```bash
brew install ollama && ollama pull nomic-embed-text   # real embeddings
ollama serve
# OPENROUTER_API_KEY set (for the chat answers)
```

Optional, only for the cross‑encoder test (free to run, heavy to install):
```bash
pip install -e .[rerank]        # or: pip install sentence-transformers
```

New config knobs (command mode — `!` toggles it):
```
rag_min_score   float   drop chunks with cosine < this (−1.0–1.0, 0 = off)
rag_top_n       int     keep this many after filter/rerank (top-N)
rag_rerank      off | cross_encoder
rag_rewrite     on | off   rewrite the question before searching
rag_k           int     candidates retrieved before filtering (top-K)
```

## Step 0 — build the index

```
index build knowledge_base name=kb strategy=structure
config set rag_index kb
```

---

## Case A — relevance filter (threshold + top‑N)

See the second stage prune weak matches for a single question:

```
config set rag_k 8
config set rag_min_score 0
config set rag_top_n 8
rag ask How do I return a 404 error in FastAPI?
```
Note the **Retrieved (top‑8)** list with cosine scores. Now tighten:

```
config set rag_min_score 0.5
config set rag_top_n 3
rag ask How do I return a 404 error in FastAPI?
```
Expect an **After filter/rerank (…)** list that is shorter — low‑score chunks
dropped, at most 3 kept. The "With RAG" answer is now grounded in fewer, cleaner
chunks. (If the cutoff removes everything, the single best chunk is kept so the
answer still has something to stand on.)

---

## Case B — measure it: precision before vs after (the comparison)

`rag eval` scores all 10 control questions and reports retrieval precision
**before** and **after** the second stage. Run it twice.

**Baseline (no filter):**
```
config set rag_min_score 0
config set rag_top_n 8
config set rag_k 8
rag eval answers=off
```
Note the summary line `Retrieval precision — before … / after …` (they'll match —
no filtering) and the `prec→` column.

**With filter:**
```
config set rag_min_score 0.5
config set rag_top_n 3
rag eval answers=off
```
Expect **precision after > before** (fewer off‑topic chunks kept) while
`Expected source retained after filtering` stays high — that's the filter doing
its job: less noise, same right answer. If retention drops a lot, your
`rag_min_score` is too aggressive — lower it.

`answers=off` keeps this free (retrieval only). Drop it (`rag eval`) to also
compare answer coverage with vs without RAG — costs ~2 chat calls per question.

---

## Case C — cross‑encoder reranker (optional)

Only after `pip install -e .[rerank]`.

```
config set rag_rerank cross_encoder
config set rag_top_n 3
rag ask How do I handle validation errors on query parameters?
```
Expect the **After filter/rerank** list to show `rerank=…` scores (from the
cross‑encoder, not cosine) and a **reordered** shortlist — the model re‑ranks the
candidates by reading each (question, chunk) pair together. First run downloads
the ~80 MB model once.

If you set `rag_rerank cross_encoder` **without** installing the package, nothing
breaks: retrieval falls back to cosine order and the notice says the reranker is
unavailable.

Turn it off again: `config set rag_rerank off`.

---

## Case D — query rewriting

```
config set rag_rewrite on
rag ask um how do i like send back a file to download
```
Expect the RAG notice / retrieval to use a cleaned query — in chat mode the
grounding notice shows `[rewritten: …]`. The rewrite turns messy phrasing into a
focused search query, usually improving what's retrieved. One extra LLM call per
question; turn off with `config set rag_rewrite off`.

---

## Case E — end-to-end in a chat thread

```
config set rag on
config set rag_min_score 0.5
config set rag_top_n 3
```
Then just chat (prompt mode). Each answer is grounded in the filtered top‑3 and
the notice reports counts, e.g.
`RAG: grounded in 3 chunk(s) from 'kb' — handling-errors.md (filtered 8→3)`.

---

## Reading the results

- **`rag ask`** shows the raw retrieved list and, when the second stage changes
  it, the filtered/reranked list — so you can see exactly what was pruned/reordered.
- **`rag eval`** summary: `precision before → after` is the headline number for
  "did the filter help?"; `retained` tells you it didn't throw away the right
  source. `hit-rate` is first‑stage recall (unchanged by filtering).
- **Chat notice** annotations: `(filtered K→N)`, `[rewritten: …]`, `[rerank: …]`
  confirm which enhancements ran.

## Tuning cheat‑sheet

| Symptom | Adjust |
|---|---|
| Answers include off‑topic chunks | raise `rag_min_score`, lower `rag_top_n` |
| Right source gets filtered out (retention drops) | lower `rag_min_score` |
| Retrieval misses the right doc entirely | raise `rag_k`, or `rag_rewrite on` |
| Ranking is topically-close but unhelpful | `rag_rerank cross_encoder` |
