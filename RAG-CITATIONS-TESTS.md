# RAG citations & "I don't know" — manual test cases

How to verify, by hand, the two new behaviors:

1. **Mandatory sources + quotes** — every grounded answer ends with a `Sources:`
   list (`source › section (chunk_id)`) and `Quotes:` (verbatim fragments from the
   found chunks).
2. **"I don't know" on weak context** — in strict mode, if nothing relevant is
   retrieved, the assistant declines and asks you to clarify instead of guessing.

> As before, judge answer *quality* with real embeddings (Ollama/OpenRouter). The
> offline `fake` provider proves the mechanics but retrieves poorly.

---

## Prerequisites

```bash
brew install ollama && ollama pull nomic-embed-text
ollama serve
# OPENROUTER_API_KEY set (for the chat answers)
```

New config knobs (command mode — `!` toggles it):
```
rag_cite           on | off   append mandatory Sources + Quotes (default on)
rag_strict         on | off   closed-domain "I don't know" mode (default off)
rag_idk_threshold  float       confidence bar; best chunk below it = weak context (default 0)
```

Build the index:
```
index build knowledge_base name=kb strategy=structure
config set rag_index kb
```

---

## Case A — mandatory sources + quotes

```
config set rag on
```
Ask (prompt mode) a question that IS in the corpus:
```
How do I return a 404 error in FastAPI?
```
Expect the answer to end with:
```
Sources:
  - handling-errors.md › Handling Errors > Use `HTTPException`  (handling-errors:structure:1)
Quotes:
  [1] handling-errors.md › Handling Errors > Use `HTTPException`: "…verbatim fragment…"
```
Check:
- **Every** grounded answer has both blocks (that's `rag_cite on`).
- Each **Source** shows `source › section (chunk_id)`.
- Each **Quote** is copied verbatim from the chunk (not paraphrased).
- The model marks which excerpts it used with `[1]`, `[2]` — only those are cited
  (falls back to all found chunks if it marks none).

You can also see it side-by-side with `rag ask`:
```
rag ask How do I return a 404 error in FastAPI?
```
The "With RAG" block shows the answer + Sources + Quotes; the "Without RAG" block
has neither. Turn citations off to compare: `config set rag_cite off`.

---

## Case B — "I don't know" on weak context (strict mode)

This is the reinforcement rule. **It's a mode**, so it never hijacks normal chat.

**First, the default (augmented) — off-topic is NOT refused:**
```
config set rag_strict off
config set rag_idk_threshold 0.5
```
Prompt mode:
```
Write me a short poem about the sea.
```
Expect a **normal answer** (a poem). The KB has nothing relevant, but augmented
mode just answers normally — it doesn't force "I don't know". This is why your
everyday chat isn't hijacked.

**Now turn on strict (closed-domain) mode:**
```
config set rag_strict on
```
Ask the same off-topic question, or something the KB lacks:
```
Write me a short poem about the sea.
```
Expect:
```
I don't know — I couldn't find confidently relevant information in the knowledge
base for this (best match scored 0.31, below the 0.50 relevance bar). Could you
clarify or rephrase? …
```
And an on-topic question still answers normally (with sources + quotes):
```
How do I return a 404 error in FastAPI?
```

So: **augmented (default)** = general assistant, RAG additive; **strict** =
closed-domain KB bot that says "I don't know" below the threshold. Tune the bar
with `rag_idk_threshold` (higher = stricter). A strict "I don't know" turn makes
**no** model call — it's deterministic and free.

---

## Case C — the 10-question check

```
config set rag_strict off        # measure grounded answers
rag eval
```
Read the new columns and the summary:
- `src` / `quo` / `mat` per question — has Sources ✓, has Quotes ✓, meaning matches ✓.
- Summary block **"Mandatory-citations checks"**:
  - **Answers with a Sources list** — should be **100%** (mandatory).
  - **Answers with Quotes** — should be **100%**.
  - **Answer meaning matches its quotes** — the lexical-overlap proxy for "does the
    answer reflect the quotes"; higher is better.

To see the "I don't know" behavior show up in the eval, run it strict with a high
bar (most control questions will then decline, proving the gate fires):
```
config set rag_strict on
config set rag_idk_threshold 0.6
rag eval
```
Watch the `rag` column show `IDK` and the summary line
`'I don't know' (weak context): N/10` climb.

`rag eval answers=off` stays free (retrieval only) but skips the citation checks
(no answers generated).

---

## What "passing" looks like

| Requirement | Where to see it | Expected |
|---|---|---|
| Sources in every answer | grounded answer / `rag eval` "Sources list" | 100% |
| Quotes in every answer | grounded answer / `rag eval` "Quotes" | 100% |
| Meaning matches quotes | `rag eval` "meaning matches" | high (real model) |
| "I don't know" on weak context | strict mode + high threshold | declines + asks to clarify |
| Normal chat not hijacked | augmented (default), off-topic question | normal answer |
