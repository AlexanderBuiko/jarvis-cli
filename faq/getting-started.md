# Getting started

## How do I install and run Jarvis?

```
pip3 install -r requirements.txt      # or: pip3 install -e .
export OPENROUTER_API_KEY=your_key    # cloud engine; skip if running fully local
jarvis                                # or: python3 -m jarvis
```

Then type in **prompt mode** (`>`) to chat, or press `!` to switch to **command
mode** and run commands like `config`, `index`, `mcp`, `help`, `support`.

## Where does Jarvis store my settings and data?

Everything is plain files under `~/.jarvis/`: threads, tasks, the profile,
invariants, and document indexes. Configuration comes from `~/.jarvis/.env`
(global) or `./.env` (project), loaded automatically at startup.

## I set OPENROUTER_API_KEY but it still says the key is missing

The key is read from the real environment first, then `./.env`, then
`~/.jarvis/.env`. Make sure the value isn't the placeholder
(`your_openrouter_key_here`) and that there are no quotes/spaces around it. Get a
free key at openrouter.ai.

## How do I get help about the product itself?

Use `help <question>` for questions about how Jarvis works (it answers from the
project docs), and `support <question> [ticket=…]` for support-style help that also
considers your ticket. Plain `help` prints the command reference.
