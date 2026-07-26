# Week 2 — Agent Internals: Context, Memory, Planning, Tools

**Source:** `transcriptions/02_agent_tools_summary.md` (+ detailed notes)
**Theme:** The four internal blocks of an agent, so you can delegate more work to
it with confidence.

## The four blocks

1. **Context management** — the agent only works with what is in context. Quality
   of context drives quality of answer.
2. **Memory management** — memory is *not* built into the model. It must be
   organised separately: save, compress, vectorise, retrieve, inject.
3. **Planning** — set a goal, split into tasks, pick a strategy, execute.
4. **Tool orchestration** — pick a tool, call it, read the result, interpret it,
   handle errors, update state.

## Context management

- **LLMs have no real memory.** Each session starts blank unless data is saved
  and re-loaded. The "it remembers me" feeling comes from external mechanisms
  (files, profiles, vector DBs) injected as context.
- **Roles and instructions are critical.** State role, task, stack, output
  format, constraints, and input files explicitly.

Techniques to manage context:

- **History compression** — summarise the dialogue into a new base. Lets you
  continue past the window limit, but loses detail and risks hallucination.
- **Sliding window** — drop old messages, keep recent. Good for a single topic,
  bad for many unrelated tasks in one chat.
- **Vector embeddings** — store data as vectors externally, pull by relevance.
  Saves the window; the basis of RAG.
- **Context layering** — split context into strategic (project) / feature /
  task layers, so the agent gets only the slice it needs.
- **Fresh dialogue** — for a truly new task, clear context and start over.
- **Tokenisation / trimming** — remove low-value tokens (politeness, repeats,
  noise). Saves the window but does not scale forever.
- **Topic branches** — split one long chat into topic branches under the hood.

Context window cost for code: one code interaction ≈ 8k–10k tokens; 1M tokens ≈
~100 such messages. Plan context management up front for code agents.

## Memory management

Memory types: **none** → **session memory** (short-term) → **long-term memory**
(recognises the user, loads past inputs). Approaches:

- **Compressed memory** — cheap, long history, easy to inject; loses detail, is
  non-deterministic.
- **Vector-based memory** — scales, keeps detail; needs extra models/compute,
  and retrieval ≠ correct reasoning.
- **Layered memory** — general / area / task levels; precise but hard to design.
- **Rule-based memory** — deterministic and controllable; rigid and costly to
  maintain.
- **Self-reflective memory** — stores meaning (style, preferences, mood, topics),
  not just facts; creates real personalisation but must be filtered and updated.

Real assistants **combine** approaches (session + vectors + rules + hierarchy +
self-reflection).

## Planning

Determine goal → split into tasks → choose strategy → re-plan if it does not fit
→ confirm plan with user → execute. This is the "Planning Mode" pattern: plan
first, user confirms, then implement.

## Tool orchestration

Tools connect the agent to the world: API, CLI, MCP servers, bash, filesystem.
Steps: pick → call → get result → **interpret** → handle errors → update state.
Interpretation is critical: a tool can return a technically correct result that
does not actually solve the task.

## Practical tips

1. Narrow context: give language, stack, task, files, constraints, output format.
2. Index and vectorise the project; load only relevant parts.
3. Document the project (comments, signatures) so the agent understands without
   full sources — saves tokens.
4. Work in stages; hand each stage to a new agent with saved state (own window).
5. Avoid frequent summarisation; prefer splitting + indexing + layering + state.

## JSON vs TOON

JSON is standard but token-heavy (field names repeat in arrays of objects).
**TOON** (Token Oriented Object Notation) declares field structure once, packs
values compactly — big savings on arrays of same-shaped objects, which matters
for per-token-billed agents.

## Maps to jarvis-cli

- Context strategies → `project_context_strategies` memory + the indexing seam.
- Layered memory / stores → `jarvis/session/` and the STM/WM/LTM model.
- Tool orchestration → `jarvis/mcp/` and `jarvis/mcp_servers/`.

## Week's assignment

Understand context management and agent memory, build a simple agent flow, learn
to manage context/state/data handling, and prepare for the MCP + tools topic.
Takeaway: a good agent is a *system* (context + memory + planning + tools + token
cost + staging), not just a model and a prompt.
