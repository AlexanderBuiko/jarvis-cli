# Jarvis — LLM Controls & Formatting Explorer

An interactive REPL-based assistant that demonstrates how **prompt-level controls** and **API-level controls** affect LLM responses.

Built as an educational project for experimenting with response formatting, length constraints, stop conditions, clarification questions, and model generation parameters.

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

## REPL Commands

| Command | Description |
|---|---|
| `help` | Show help |
| `config show` | Show current configuration |
| `config set <key> <value>` | Change a config value |
| `config reset` | Reset all settings to defaults |
| `session results` | Show all interactions from this session |
| `exit` / `quit` | Exit Jarvis |

Any other input is sent to the LLM as a question.

---

## Configuration System

Jarvis uses **three configuration layers**, applied in order:

1. **Internal defaults** — built into the code  
2. **Persisted user config** — stored in `~/.jarvis/config.json`  
3. **Runtime overrides** — applied via `config set` during the session  

All changes via `config set` are persisted automatically. You never edit the JSON file manually.

---

## Configuration Reference

### Generation parameters (API-level)

| Key | Default | Description |
|---|---|---|
| `temperature` | `0.2` | Sampling temperature (0.0 – 2.0) |
| `top_p` | `0.9` | Nucleus sampling (0.0 – 1.0) |
| `top_k` | `40` | Top-k sampling |
| `max_tokens` | `200` | Maximum tokens in the response |
| `seed` | `none` | Random seed for reproducibility |

### Prompt-level controls

| Key | Default | Description |
|---|---|---|
| `response_format` | `plain` | `plain`, `bullet_list`, `numbered_list` |
| `max_words` | `200` | Max words injected as a prompt instruction |
| `clarification_questions` | `0` | Questions to ask before answering |

### Stop controls

| Key | Default | Description |
|---|---|---|
| `prompt_stop_enabled` | `false` | Inject stop marker instruction in prompt |
| `api_stop_enabled` | `false` | Send stop sequence to the API |
| `stop_sequence` | `###END###` | The stop string used by both mechanisms |

### Control mode

| Key | Default | Description |
|---|---|---|
| `control_mode` | `both` | `prompt`, `api`, or `both` |

**`control_mode` explained:**
- `prompt` — only prompt-level instructions are active (format, length, stop marker)
- `api` — only API parameters are sent (temperature, max_tokens, stop, etc.)
- `both` — both types of controls are active simultaneously

---

## Example Session

```
jarvis> help

jarvis> config show

  temperature  =  0.2
  top_p        =  0.9
  max_tokens   =  200
  ...

jarvis> config set response_format bullet_list
Updated: response_format = bullet_list

jarvis> config set clarification_questions 2
Updated: clarification_questions = 2

jarvis> Plan a trip to Japan

A: Question 1 of 2: What is your total budget for the trip?

jarvis> 2000 USD

A: Question 2 of 2: How many days are you planning to travel?

jarvis> 10

A:
• Budget: $2,000 for 10 days — feasible with budget accommodation
• Flights: Book in advance, expect $800–$1,200 round-trip
• Stay: Hostels or capsule hotels ~$30–50/night
• Food: Street food and convenience stores keep costs low
• Transport: Get an IC card; JR Pass may not be cost-effective at this length

jarvis> config set clarification_questions 0
Updated: clarification_questions = 0

jarvis> config set temperature 1.2

jarvis> Explain Docker

A: ...

jarvis> session results

────────────────────────────────────────────────────────────
  Interaction #1
...

jarvis> exit
Goodbye.
```

---

## How Controls Work

### Prompt-level controls

Injected as natural-language instructions inside the **system prompt**:

```
You are Jarvis, a helpful and concise assistant.
Format your response as a bullet list.
Keep your response to a maximum of 200 words.
When you have finished your response, write exactly "###END###" on its own line.
```

The model is *instructed* to follow these rules but is not technically prevented from violating them.

### API-level controls

Passed as parameters in the **API request body**:

```json
{
  "model": "anthropic/claude-sonnet-4",
  "temperature": 0.8,
  "top_p": 0.9,
  "max_tokens": 200,
  "stop": ["###END###"]
}
```

These are enforced by the model runtime — `max_tokens` and `stop` are hard limits.

### Experimenting with the difference

Try the same question under different `control_mode` settings:

```
config set control_mode prompt    → only instructions in prompt
config set control_mode api       → only API parameters
config set control_mode both      → both active
```

Then compare outputs with `session results`.

---

## Project Structure

```
jarvis/
├── __init__.py
├── __main__.py          ← entry point
├── config/
│   ├── schema.py        ← JarvisConfig dataclass
│   └── manager.py       ← three-layer config management + persistence
├── openrouter/
│   └── client.py        ← HTTP client for OpenRouter API
├── prompt_builder/
│   └── builder.py       ← dynamic prompt construction
├── repl/
│   ├── commands.py      ← built-in command handlers
│   └── loop.py          ← REPL loop + LLM interaction flow
└── session/
    └── store.py         ← in-memory session history
requirements.txt
setup.cfg
README.md
```

---

## Model

Hardcoded to `anthropic/claude-sonnet-4` via OpenRouter. No tools, no function calling, no streaming.
