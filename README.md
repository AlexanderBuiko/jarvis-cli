# Jarvis — Conversational AI Agent

An interactive CLI agent that holds multi-turn conversations via the OpenRouter API.

---

## Quick Start

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Set your OpenRouter API key

```bash
export OPENROUTER_API_KEY=your_key_here
```

Get a free key at [openrouter.ai](https://openrouter.ai).

### 3. Install Jarvis as a CLI tool (optional)

```bash
pip3 install -e .
```

### 4. Run

```bash
# If installed:
jarvis

# Or directly:
python3 -m jarvis
```

---

## Commands

| Command | Description |
|---|---|
| `help` | Show help and parameter reference |
| `config show` | Show active configuration |
| `config set <key> <value>` | Set a parameter |
| `config update <k=v> …` | Set multiple parameters at once |
| `config reset` | Clear all parameters (revert to API defaults) |
| `history` | Show current conversation history |
| `history clear` | Clear conversation history |
| `session chat` | Show the full conversation transcript |
| `session summary` | Show aggregate statistics (tokens, model, config) |
| `session api` | Show raw API request/response payloads with per-call metrics |
| `exit` / `quit` | Exit Jarvis |

Any other input is sent to the agent as a message.

### Input & status

- The input line **soft-wraps** as you type and grows up to 5 rows for longer messages.
- Pasting a large block (≥ 1000 characters) collapses it to `[Pasted from clipboard: N characters]` in the line; the full text is restored when you send.
- While a request is running, a **spinner with elapsed time** shows that work is in progress and input isn't expected.
- The status line shows context-window usage in tokens.
- `model` and `context_strategy` are **locked once a thread has messages** — change them on a fresh thread (`thread new` / `thread clear`).

---

## Configuration

Parameters are optional. When none are set, OpenRouter API defaults apply.
Set only what you want to change.

| Parameter | Type | Description |
|---|---|---|
| `model` | str | OpenRouter model identifier. Default: `anthropic/claude-sonnet-4` |
| `temperature` | float 0.0–2.0 | Sampling temperature |
| `top_p` | float 0.0–1.0 | Nucleus sampling probability |
| `top_k` | int | Top-k sampling cutoff |
| `max_tokens` | int | Maximum tokens in the response |
| `seed` | int \| none | Random seed for reproducibility |
| `solution_strategy` | see below | Controls how the agent approaches the problem |

### Solution strategies

| Strategy | Behaviour |
|---|---|
| `direct` | Answer immediately (default) |
| `step_by_step` | Reason through steps explicitly before answering |
| `expert_panel` | Three-expert panel discussion with a synthesised final answer |
| `prompt_generation` | Stage 1: generate an optimised prompt for the task. Stage 2: answer using it |

---

## Conversation

Jarvis maintains conversation history across turns. Each message you send includes all prior turns so the model retains full context.

```
jarvis> What is HTTP?

A: HTTP (HyperText Transfer Protocol) is the foundation of data
   communication on the web...

jarvis> Can you explain the request/response cycle in more detail?

A: Sure. When a client sends an HTTP request it includes...

jarvis> history

Conversation history (2 turns)
········································
  [1] You   : What is HTTP?
  [1] Jarvis: HTTP (HyperText Transfer Protocol) is...
········································
  [2] You   : Can you explain the request/response cycle in more detail?
  [2] Jarvis: Sure. When a client sends an HTTP request...
········································

jarvis> history clear
Conversation history cleared.
```

---

## Example Session

```
jarvis> config set model anthropic/claude-haiku-3
Updated: model = anthropic/claude-haiku-3

jarvis> config set solution_strategy step_by_step
Updated: solution_strategy = step_by_step

jarvis> How does TLS handshake work?

A: Step 1: The client sends a ClientHello...

jarvis> session api

────────────────────────────────────────────────────────────
  Interaction #1
...

jarvis> exit
Goodbye.
```

---

## Tasks: a finite state machine

A *task* is a managed process, not a loose chain of prompts. It moves through a
finite state machine whose transitions are enforced **in code**, so the rules
survive summarisation, compaction and thread switches:

```
clarification → planning → execution → validation → done
                    ↑___________|            |
                  (replan)              (rework: back to execution)
```

Each task persists its **phase** (stage), **current step** and **expected
action**, plus the approved plan and each stage's result — so work can be paused
at any phase and resumed later (even in a brand-new chat thread) without
re-explaining anything.

Each stage is owned by a **stage agent** (clarifier, planner, executor,
validator) — a small class with an input contract, an output contract, a system
prompt and (later) tools. An **orchestrator** drives the FSM across these agents.

**Tasks and chat are two separate surfaces.** Threads (`thread …`) are pure
conversation, no pipeline. A **task is a standalone workspace** with its own
context, independent of threads: you *enter* it to work the pipeline and *exit*
back to chat. Inside a task your messages drive its pipeline; outside, they're
normal chat. The two never cross-contaminate.

| Command | Description |
|---|---|
| `task new [name]` | Create a task workspace **and enter it** |
| `task start <name-or-id>` | Enter an existing task workspace |
| `task run` | Continue the entered task with no new input |
| `task exit` | Leave the task, back to chat (state preserved) |
| `task show` / `task list` | Inspect task state |

Inside a task, **your next message drives it**, and `task run` continues with no
new input. The pipeline **pauses only when it needs you**:

- a **free-text question** — clarification, or an execution step that needs input;
- a **Confirm / Reject** choice at the two critical gates — **plan approval** and the
  final **done** decision. The choices show vertically with an arrow (↑/↓ to move,
  Enter to select). **Reject** asks *"What's the problem?"* and reworks with your
  feedback (plan → regenerate; done → back to execution).

Everything in between — clarification→planning, each execution step,
execution→validation — runs **automatically**. Every transition still goes through
the code-enforced `ALLOWED_TRANSITIONS`; the model never moves itself.

**Live execution.** Planning parses the plan into discrete steps; execution then
works **one step per turn** under a **live step table** above the input
(✓ completed · ▶ in-progress · ○ pending) that redraws in place as each step
finishes, with a spinner + timer beneath it. Press **Ctrl+C** to stop — the last
completed step is saved, and `task run` resumes from there.

**The result.** Execution shows concise status, not raw output. At **done** the
agent assembles the complete deliverable; a **short summary** is shown and the full
deliverable is **saved to a result file** (`~/.jarvis/tasks/results/<id>.md`, whose
path is printed and also shown in `task show`).

## Architecture

```
__main__.py           ← wires agent + REPL, starts the application
agent.py              ← JarvisAgent: conversation, memory, LLM gateway
llm/
  engine.py           ← LLMEngine interface (provider-independent)
  accounting.py       ← per-call cost/usage records
openrouter/
  client.py           ← OpenRouter implementation of LLMEngine
pipeline/
  base.py             ← StageAgent contract + control-marker grammar
  stages.py           ← clarifier / planner / executor / validator agents
  orchestrator.py     ← drives the task finite state machine
  invariants.py       ← InvariantChecker (natural-language requirements linter)
config/
  manager.py          ← validated key-value configuration store
prompt_builder/
  builder.py          ← system prompt + working-memory block construction
repl/
  loop.py             ← REPL loop: reads input, calls agent, prints output
  commands.py         ← built-in command handlers
session/
  store.py            ← in-memory session log
  task_store.py       ← task FSM persistence (ALLOWED_TRANSITIONS)
```

Following the "build from abstractions" principle, the agent, orchestrator and
stage agents depend on the `LLMEngine` interface rather than any concrete
provider — so OpenRouter (or a fake engine, in tests) plugs in behind the same
contract. `JarvisAgent` remains the central entity: the REPL is a thin UI layer
that calls `agent.chat()` for free-form input and `agent.run_task()` for the
pipeline.

## Tests

```
python -m unittest discover -s tests -t .
```

Pure unit tests plus integration tests that drive the real agent against a
`FakeEngine` (no network), covering the FSM transitions, stage contracts,
orchestrator autonomy/gates, and the pause/resume behaviours.
