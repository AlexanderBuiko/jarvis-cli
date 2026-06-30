# RAG chat mode — manual test cases

How to verify, by hand, that Jarvis answers from your **local Markdown files** when
RAG is on, and from the model's **general knowledge** when it is off.

Each case is run twice — once with `rag off`, once with `rag on` — so you can see
the difference. With RAG on, the answer is grounded in the indexed `.md` files and
cites them as `filename › section`, and a per-turn notice shows which sources were
used (e.g. `RAG: grounded in 4 chunk(s) from 'kb' — handling-errors.md, …`).

---

## Prerequisites

**Embeddings provider.** RAG needs an embedder for both *building* the index and
*embedding your question*. Pick one:

- **Ollama (default, local, free)** — recommended:
  ```bash
  brew install ollama
  ollama pull nomic-embed-text
  ollama serve          # if it isn't already running
  ```
- **OpenRouter (cloud, costs money)** — set in `.env`:
  ```
  JARVIS_EMBED_PROVIDER=openrouter
  OPENROUTER_API_KEY=...   # already required for chat
  ```
- **Fake (offline, mechanics only)** — `JARVIS_EMBED_PROVIDER=fake`. Proves the
  wiring without a real model, but retrieval quality is poor — don't judge answer
  quality with this.

**REPL modes.** Jarvis starts in **prompt mode** (`>`, your message goes to the
agent). Type `!` on an empty line to switch to **command mode** (for `config`,
`index`, …), and `!` again to switch back. Below, lines under "command mode" are
run after switching; questions are asked in prompt mode.

---

## Step 0 — build the index (once)

Command mode:

```
index build knowledge_base name=kb strategy=structure
index list
```

Expect: `Built index 'kb' … documents: 25 … chunks: ~305`, and `kb` shown by
`index list`. (You can also try `strategy=fixed` into a second name and compare
with `index compare knowledge_base query=...`.)

---

## Case A — a question answered by the local docs (grounding + citations)

**Without RAG** (command mode):
```
config set rag off
```
Prompt mode:
```
How do I return a 404 error in FastAPI?
```
Expect: a correct but **generic** answer from the model's training. **No source
citations**, **no `RAG: grounded` notice**.

**With RAG** (command mode):
```
config set rag on
config set rag_index kb
```
Prompt mode (ask the same thing):
```
How do I return a 404 error in FastAPI?
```
Expect: the answer is drawn from the indexed excerpts and **cites**
`handling-errors.md › …`, and you see a notice like
`RAG: grounded in 5 chunk(s) from 'kb' — handling-errors.md, …`.

More questions that map cleanly to a local file (try each both ways):

| Question | Local source you should see cited |
|---|---|
| "What status code does FastAPI use by default for a POST?" | `response-status-code.md` |
| "How do I declare a query parameter as required?" | `query-params*.md` |
| "How do I serve static files?" | `static-files.md` |
| "How do I run background tasks after returning a response?" | `background-tasks.md` |

---

## Case B — a question **not** in the knowledge base (isolation)

This shows RAG stays grounded instead of inventing.

**With RAG on** (from Case A), prompt mode:
```
What is the capital of France?
```
Expect: because the FastAPI docs say nothing about France, the answer should say
the **knowledge base doesn't cover this** (per the block's instruction), rather
than confidently answering. The notice will still list whatever low-relevance
chunks were retrieved.

**With RAG off**, the same question is answered normally ("Paris"). The contrast
shows RAG is constraining answers to your corpus.

---

## Case C — the unmistakable demo: a fact the base model cannot know

The clearest proof. Add a document containing an **invented** fact, re-index, and
ask about it. The base model has never seen it, so only RAG can answer correctly.

1. Create a one-file mini-corpus (shell):
   ```bash
   mkdir -p rag_demo
   cat > rag_demo/acme-policy.md <<'EOF'
   # ACME Engineering Handbook

   ## Code Review Policy

   At ACME, every pull request requires **exactly three approvals** before merge,
   and the maximum allowed review time is **17 hours**. The secret deploy keyword
   is "purple-otter-92".
   EOF
   ```

2. Build an index for it (command mode):
   ```
   index build rag_demo name=acme strategy=structure
   ```

3. **Without RAG** (command mode `config set rag off`), prompt mode:
   ```
   What is ACME's code review policy and the deploy keyword?
   ```
   Expect: the model **does not know** — it guesses, gives a generic code-review
   answer, or says it has no information. It will **not** produce
   "three approvals / 17 hours / purple-otter-92".

4. **With RAG** (command mode):
   ```
   config set rag on
   config set rag_index acme
   ```
   Prompt mode (same question):
   ```
   What is ACME's code review policy and the deploy keyword?
   ```
   Expect: the exact facts — **three approvals**, **17 hours**,
   **purple-otter-92** — with a citation to `acme-policy.md › … Code Review Policy`
   and a `RAG: grounded …` notice.

This is the lecture's "code review policy" scenario: same model, but RAG injects
your private knowledge at inference time.

---

## Reading the result

- **Notice line** (after the answer): `RAG: grounded in N chunk(s) from '<index>' — <files>`
  confirms retrieval ran and which files fed the answer. Other notices —
  `index … not found`, `no rag_index is set`, `retrieval failed …` — mean RAG was
  on but couldn't retrieve, so the turn answered **without** grounding (it never
  breaks the chat).
- **Citations** in the answer body (`filename › section`) come from chunk metadata.
- **No notice + no citations** = you're getting the model's general answer
  (`rag off`).

## Toggle reference

```
config set rag on | off       Enable/disable grounding for this thread
config set rag_index <name>    Which index to retrieve from ('index list')
config set rag_k <1-20>        How many chunks to retrieve (default 5)
config show                    See current values
```

RAG is a runtime flag — flip it on/off between messages in the same thread to
compare answers directly.
