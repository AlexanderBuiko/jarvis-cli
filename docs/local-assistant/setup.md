# Day 4 — local LLM as an IDE code assistant

Goal: run a local model in PyCharm for **autocomplete + chat**, fed the Day-1
rules as its system prompt, then run the Day-1 and Day-2 tasks on it and compare
against the cloud assistant. Fill [comparison.md](comparison.md) as you go.

Bundle chosen: **Ollama + Continue plugin (JetBrains)** — you already have both a
JetBrains IDE and Ollama, so no VS Code install. The config is identical if you
ever switch to VS Code.

## 1. Start Ollama and pull the models

```bash
ollama serve &                                    # daemon (skip if already running)
ollama pull qwen2.5-coder:1.5b-base               # autocomplete (FIM), ~1 GB
ollama pull qwen2.5-coder:7b                       # chat #1, ~4.7 GB
ollama pull deepseek-coder-v2:16b-lite-instruct-q4_0   # chat #2, ~8.9 GB
ollama pull qwen2.5-coder:14b                      # chat #3, ~9 GB
```

Pull only what you want to test — #1 is enough to start. Total for all four ≈ 24 GB
on disk (not RAM; only the loaded model uses RAM).

## 2. Install the Continue plugin in PyCharm

`Settings → Plugins → Marketplace → search "Continue" → Install → restart`.
A Continue panel appears in the right sidebar.

## 3. Wire in the config

```bash
mkdir -p ~/.continue
cp docs/local-assistant/config.yaml ~/.continue/config.yaml
```

The config references `docs/local-assistant/system-prompt.md` by absolute path,
so that committed file **is** the live system prompt — edit it there, no re-copy.
Reload: Continue panel → gear icon → the models appear in the model dropdown.

Verify autocomplete is on: open any `.py` file, start typing — grey ghost text
should appear. Verify chat: pick "Qwen2.5 Coder 7B" in the dropdown, ask
"what does jarvis/llm/router.py do?" after `@`-mentioning the file.

## 4. Run the tasks and compare

The full runbook — the two fixed task prompts, the per-model loop, the timing
method, the scoring checklist, and how the scores become the table — is in
**[run-guide.md](run-guide.md)**. Capture raw numbers in
[results-raw.md](results-raw.md); assemble the final table in
[comparison.md](comparison.md).

(Task B was rewritten: the old "negative max_tokens" bug is already fixed on this
branch, so it's a no-op. The live agent-mode task is "add the `presence_penalty`
config parameter end-to-end" — see the run guide.)

## Agent mode: if the model prints tool-call JSON instead of applying edits

Symptom: in Agent mode the model outputs a ```json block like
`{"name": "edit_existing_file", ...}` with an "Apply" button, and nothing is
actually edited. The model is *describing* a tool call as text; Continue never
executes it. (It will also hallucinate file paths, because it never really searched.)

Cause + fix, in order:
1. **The model must support tools natively.** Check:
   ```bash
   ollama show qwen2.5-coder:7b        # look for "tools" under Capabilities
   ```
   `qwen2.5-coder:7b`/`:14b` list `tools`. **`deepseek-coder-v2` does NOT** — it
   can't do agent mode at all; use it in Chat only.
2. **Force the native tool path** — already done in `config.yaml`:
   `capabilities: [tool_use]` on each chat model. Re-copy the config and reload
   Continue if you edited it before this was added.
3. **Keep "System Message tools" OFF** for a tool-capable model. When it is ON,
   Continue injects tool descriptions as text and expects one exact reply format;
   qwen2.5-coder wraps its call in a ```json block instead, which Continue does not
   parse — so it renders a code block with "Apply" and nothing runs. Confirm the
   mode in `~/.continue/logs/prompt.log`: a `You are in agent mode` /
   `systemMessageDescription` block in the system prompt = system-message mode is on.
   Only turn it ON for models that have *no* native `tools` capability.
4. **Tool policies = Automatic** (Continue settings) so it doesn't stop to ask.

Reality: Continue + Ollama agent-mode tool execution is a known-flaky combination.
If neither path drives the edits, that is the **finding**, not a setup error:
record "local could plan/describe tool calls but not execute the agent loop" in the
**Agent mode** row. To still score code *quality* for Task B, run the same prompt in
**Chat** mode and Apply the blocks by hand (or Edit mode, `Cmd/Ctrl+I`, per file),
then diff against `submission/day4/cloud-baseline.diff`.

## Tuning knobs (if quality/speed is off)

| Symptom | Knob |
|---|---|
| Model forgets earlier context | `num_ctx` too low — already 8192; raise per model, watch RAM |
| Answers wander / invent APIs | temperature already 0.1; lower `topP` to 0.8 |
| Autocomplete laggy | drop to `qwen2.5-coder:1.5b-base`, close other chat models |
| RAM pressure (14B) | run one chat model at a time; `ollama stop <model>` to unload |
| Too little project context | `@`-mention more files, or lean on `repo-map` |
