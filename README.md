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

## Architecture

```
__main__.py           ← wires agent + REPL, starts the application
agent.py              ← JarvisAgent: conversation history, request pipeline
openrouter/
  client.py           ← HTTP transport for OpenRouter API
config/
  manager.py          ← validated key-value configuration store
prompt_builder/
  builder.py          ← system prompt and strategy prompt construction
repl/
  loop.py             ← REPL loop: reads input, calls agent, prints output
  commands.py         ← built-in command handlers
session/
  store.py            ← in-memory session log
```

`JarvisAgent` is the central entity. The REPL is a thin UI layer that calls `agent.chat()` for every non-command input. Conversation history lives on the agent and is included in every API request automatically.
