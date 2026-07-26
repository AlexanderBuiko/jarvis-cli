# Mini-chat with RAG + sources + task memory — manual test cases

The "mini-chat" is the existing `jarvis` CLI chat with three things turned on:

- **history** — threads persist the dialogue (already built in),
- **RAG + sources** — `rag on` retrieves per question and every answer ends with
  `Sources:` / `Quotes:` (the citations feature),
- **task memory** — the new `dialogue_state` context strategy keeps a structured
  **Goal / Given / Constraints** block, updated each turn, so a long chat never
  loses its purpose.

> Use a real embedder (Ollama/OpenRouter) to judge answer quality; the offline
> `fake` provider proves the mechanics.

---

## Prerequisites & setup

```bash
brew install ollama && ollama pull nomic-embed-text
ollama serve
# OPENROUTER_API_KEY set (for chat answers)
```

Build the index once, then turn on the mini-chat (command mode — `!` toggles it).
`context_strategy` can only be set on an **empty** thread, so do this first:

```
index build knowledge_base name=kb strategy=structure
thread new minichat
config set context_strategy dialogue_state
config set rag on
config set rag_index kb
```
Now just chat in prompt mode (`>`). That's the mini-chat.

---

## Case A — RAG + sources + history in a normal chat

Ask a few related questions:
```
How do I return a 404 error in FastAPI?
And a 401 for bad credentials?
How do I test that endpoint?
```
Check each answer:
- is grounded in the docs and ends with a **`Sources:`** list + **`Quotes:`**,
- the **history** carries over (later answers build on earlier turns).

`thread` shows the running conversation; `session summary` shows token/cost.

---

## Case B — task memory (Goal / Given / Constraints)

After a few turns, run:
```
thread state
```
Expect the structured block, e.g.:
```
Task State (dialogue memory)
Goal: <your objective, inferred from the chat>
Given: <details you've specified so far>
Constraints: <fixed terms/limits agreed so far>
```
As you add details ("tokens expire in 30 minutes", "must stay Python 3.12"), run
`thread state` again — **Given** and **Constraints** accumulate, and **Goal**
stays stable. It's also visible in `thread summary` under "Task State".

---

## Case C — the mentor's check: two long scenarios (10–15 messages)

### C0 — Define the actual context first (do this before running either scenario)

The result of a scenario depends entirely on the config you start with, so set it
up explicitly. `context_strategy` is locked once a thread has messages, so start a
fresh thread and configure it before the first message:

```
thread new items-api
config set context_strategy dialogue_state
config set rag on
config set rag_index kb
config set rag_strict off
```

**Calibrate the relevance bar** so that questions the KB *covers* get grounded
(with sources), while questions it *doesn't* fall back to general knowledge
instead of deflecting to irrelevant chunks. Probe one in-KB and one off-KB
question and read the top `Retrieved` cosine scores:

```
rag ask How do I return a 404 error?            # in the corpus  → high top score (~0.6–0.8)
rag ask How do I set up JWT authentication?     # not in corpus  → lower top score (~0.4–0.5)
```
Set the threshold *between* those two bands, then confirm:
```
config set rag_idk_threshold 0.55
config show
```
Now every turn does one of two things, and you know which to expect:
- top score **≥ 0.55** → grounded answer **with `Sources:`**,
- top score **< 0.55** → **general-knowledge** answer + a "not in KB" notice (no sources).

> Without this step (threshold left at 0) every question grounds against whatever
> came back — so off-topic questions deflect with "the KB doesn't cover this." That
> is the calibration, not a bug.

---

### Scenario 1 — in-corpus goal (every turn grounded, sources throughout)

Goal: **build a FastAPI items API**. Every question maps to a corpus file, so this
is the clean "sources on every turn" demonstration.

```
I'm building a FastAPI API to manage items.
How do I declare a path parameter for the item ID?
Require that item ID to be greater than 0.
Add a query parameter with a maximum length.
How do I accept the item as a request body?
Return a response model that hides internal fields.
Return a 404 when the item doesn't exist.
What status code should creating an item return?
Let users upload an image file for an item.
Add CORS so my frontend can call the API.
How do I test these endpoints?
Recap the API we've designed so far.
```
Expect: **every** answer ends with `Sources:` / `Quotes:`, and at message 12 the
recap still reflects the original goal plus the constraints you added (ID > 0, max
length, hidden fields, CORS…). `thread state` shows a stable Goal.

---

### Scenario 2 — mixed / partly off-corpus goal (shows the fallback + memory)

Goal: **secure the items API with auth** — which the corpus mostly does *not*
cover. Start a new thread and re-configure (same C0 steps, `thread new secure-api`).

```
I want to add authentication to my items API.
Use OAuth2 with the password flow.
How do I hash passwords?
Tokens should expire in 30 minutes.
How do I return a 401 on bad credentials?
Keep everything Python 3.12.
How do I add CORS for the login page?
How do I test the login endpoint?
How do I handle refresh tokens?
Add a /users/me endpoint.
What should I put in the JWT payload?
Recap what we've decided.
```
Expect a **mix**, and that's the point:
- auth-specific turns (hashing, OAuth2, JWT, refresh tokens) fall below the bar →
  **general-knowledge** answers with the "not in KB" notice, **no sources**;
- turns that touch covered topics (401 → `handling-errors.md`, CORS → `cors.md`,
  testing → `testing.md`) come back **grounded with `Sources:`**.

Crucially, across all 12 messages the **Goal stays "add authentication to the
items API"** and the constraints accumulate (30-min tokens, Python 3.12) — verify
with `thread state` and the final "Recap".

---

### What to verify (both scenarios)

1. **Purpose is not lost** — at message ~12, the recap reflects the original goal
   and every constraint you fixed. `thread state` shows the Goal unchanged and the
   accumulated Given/Constraints.
2. **Grounding behaves per the threshold** — in-KB turns end with `Sources:`;
   off-KB turns answer from general knowledge with the "not in KB" notice. Scenario
   1 should be sources-throughout; Scenario 2 a deliberate mix.

That's the requirement: *the assistant doesn't lose its purpose, and grounds its
answers in sources whenever the knowledge base actually covers the question.*

---

## What "passing" looks like

| Requirement | Where to see it | Expected |
|---|---|---|
| Stores dialogue history | `thread` | full transcript persists |
| RAG context per question | grounding notice per turn | `RAG: grounded …` (or the "not in KB" notice when below the bar) |
| Displays sources when grounded | in-KB answers | `Sources:` + `Quotes:`; off-KB answers fall back to general knowledge + a "not in KB" notice |
| Task memory: goal/given/constraints | `thread state` | structured block, goal stable |
| Doesn't lose purpose over 10–15 msgs | recap at the end | still on the original goal |

## Notes

- `dialogue_state` keeps the **full** history plus the state block, which is ideal
  for 10–15 messages. For much longer chats you'd combine it with compression —
  that would be a follow-up (context strategies are currently exclusive).
- Task memory costs one extra small model call per turn (the state update), like
  `sticky_facts`.
