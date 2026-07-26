# Week 1 — AI Basics, Prompting and Agents

**Source:** `transcriptions/01_ai_prompting_summary.md` (+ detailed notes)
**Theme:** Understand how LLMs, agents, code assistants, and generation parameters
work, so you can choose a model and a technique on purpose.

## Core terms

- **LLM** — the large language model itself. The model, not the interface.
- **Code assistant** — the tool that writes code (Claude Code, Cursor, Codex,
  Copilot). It is an *interface* to an LLM; it can live in a CLI, an IDE, or its
  own app.
- **Agent** — an AI entity bounded by a context and a task.
- **Sub-agent** — a specialised agent inside a larger system, living in its own
  context window, owning one area (backend, tests, design…).
- **Skill** — one small ability the agent uses: call a tool, run a command, get
  a result.
- **Swarm** — many small agents, each doing a tiny task, returning results to a
  main orchestrator.
- **Context window** — the token budget the model can process before meaning is
  lost. Over the limit, context is dropped or summarised.
- **Token** — the unit text is split into, on both input and output.

## Prompting techniques

- **Simple prompting** — one request, one answer. Rare in pure form today.
- **Chain of Thought** — ask the model to lay out its reasoning; raises answer
  quality because it reasons before answering.
- **Deliberate reasoning / multi-prompting** — look at one question from several
  roles (physicist, architect, …). Combines well with Chain of Thought.
- **Meta-prompting** — one model writes a detailed prompt for another model.
  Useful to first gather stack, constraints, and requirements.
- **Swarm prompting** — several models/agents answer, then results are merged.

## The agent loop

```
perception → memory → reasoning → planning → action → feedback
```

- **Perception** — inputs: prompt, API, text, sensors.
- **Memory** — long-term store: files, DBs, saved context.
- **Reasoning** — combine input + memory, apply inference techniques.
- **Planning** — set a goal, split into steps.
- **Action** — the visible result: code, text, a tool call.
- **Feedback** — did it fit; what to change for the next pass.

Key point: what the user sees is already the **Action** stage. The real work
happens before the visible output.

## Generation parameters

- **Temperature** — predictability vs creativity. Low = precise and dry; high =
  varied and creative.
- **Top-P** — cut token candidates by probability weight, keep the likely ones.
- **Top-K** — cap the number of candidates for the next token.
- **Max tokens** — output length cap. Bigger is costlier and not always better.
- **Seed** — randomness seed; controls reproducibility.
- **Frequency / presence penalty** — punish repetition so the model does not
  loop on the same words.

## Prompt roles

- **system prompt** — the session core; sets role and behaviour frame.
- **user prompt** — the user message.
- **assistant prompt** — the model reply.

One system prompt, many user/assistant turns. Overriding the system prompt sets
a new frame for the model.

## Choosing a model — five axes

1. **Parameter count** — size/complexity (up to ~1T params).
2. **Inference speed** — tokens per second. Local on weak hardware is slow.
3. **Context length** — advertised huge windows are not always usefully huge.
4. **Reasoning quality** — depends on architecture, training, task fit.
5. **Economics** — cost per 1M tokens. With many API calls this dominates.

Takeaway: a new architecture, a big window, or high speed do not by themselves
make a better model. **Fit to the task** matters more.

## Maps to jarvis-cli

- Generation params live in `jarvis/config/` (`ConfigManager`), e.g.
  `temperature`, `presence_penalty`, `max_tokens`, exposed via `config set`.
- The `LLMEngine` Protocol (`jarvis/llm/engine.py`) is the seam that lets any
  provider (OpenRouter, Ollama) plug in — the practical form of "choose a model
  on purpose".

## Week's assignment

Set up agents, get answers from an LLM, experiment with temperature / Top-P /
Top-K, try different prompts, understand model differences, and learn to pick an
LLM for a real task. An exploratory week: feel the models first, then use them
deliberately later.
