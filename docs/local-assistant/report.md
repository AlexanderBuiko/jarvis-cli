# Day 4 — Local Boost: report

**Goal:** run a local LLM as an IDE code assistant (autocomplete + chat), feed it
the Day-1 rules as a system prompt, run the Day-1 and Day-2 tasks on it, and
compare against the cloud assistant.

**Outcome in one line:** the setup was built and works; **autocomplete is a
measured local win**; on the two coding tasks **both local chat models (7B and
14B) failed to produce applyable, in-style code**, while the cloud baseline passed
cleanly. The comparison is completed with measured data (cloud, 7B, 14B,
autocomplete) plus labelled hardware estimates only for the raw tok/s speed rows.

---

## 1. What was set up  (delivered)

| Piece | Choice | Where |
|---|---|---|
| Bundle | Ollama + Continue plugin in **PyCharm** (no VS Code needed) | — |
| Machine | Apple **M4 Pro, 24 GB** | — |
| Chat models run | `qwen2.5-coder:7b`, `qwen2.5-coder:14b` | pulled + run |
| Autocomplete | `qwen2.5-coder:1.5b-base` (FIM) | pulled + run |
| Not run | `deepseek-coder-v2:16b-lite` — no `tools` cap → no agent mode | — |
| System prompt | Day-1 rules, **code-style slice only** | [system-prompt.md](system-prompt.md) |
| Config | models + roles, `temperature 0.1 / top_p 0.9`, `num_ctx 8192`, rules→file | [config.yaml](config.yaml) |

Setup steps: [setup.md](setup.md). Runbook: [run-guide.md](run-guide.md).
Full run notes: [results-raw.md](results-raw.md). Table: [comparison.md](comparison.md).

## 2. What was run

**Cloud baseline — [MEASURED, passed].** Claude Code did both tasks:
- Task A (add `models` command): all 5 registration points, house-style clean.
- Task B (add `presence_penalty` param): found all 4 registration points unaided,
  matched the existing `_active_provider_model` idiom without being shown it.
- Verified: **469/469 tests pass, ruff clean, first run.** Exact code:
  `submission/day4/cloud-baseline.diff`.

**Autocomplete — qwen2.5-coder:1.5b-base — [MEASURED, works].** Single-file-context
test passed: it completed distinctive in-file symbols rather than generic guesses,
at keystroke-speed latency. Recorded on video. **This is the local bright spot.**

**Local chat — qwen2.5-coder:7b — [MEASURED, failed].** Chat and agent mode.
Task A → invented a `main.py` / `list_models()` with `print` and `model1`/`model2`
fake data; never referenced a real project symbol. Task B → hallucinated a
`register_config_param` function; before the tool-calling fix the search printed as
text and never ran. Zero applyable output.

**Local chat — qwen2.5-coder:14b — [MEASURED, failed, but better process].**
- Task A (chat): **identical failure to the 7B** — `main.py`, `print`,
  OpenAI/Hugging Face fake data. Bigger model, no quality gain.
- Task B (agent): the one real improvement — native tools fired, it ran a codebase
  search and surfaced the **real** files `jarvis/repl/commands.py` and
  `jarvis/repl/loop.py`. But it then invented a `validate_config()` function,
  edited the **wrong files** (config params live in `jarvis/config/manager.py`),
  ignored the `_PARAM_PARSERS`/`_PARAM_VALIDATORS` pattern, and wrote tests for the
  invented function. 0/4 registration points correct.

## 3. Why the local runs failed  (root cause)

- **Agent tool execution needs the right switches.** Continue + Ollama only
  executes tools with **"System Message tools" OFF** (native path) *and*
  `capabilities: [tool_use]` in the config. With System Message tools on, the model
  prints tool-call JSON as text and nothing runs. Once fixed, tools executed (the
  14B's codebase search proves it).
- **The models lack project grounding, and size didn't fix it.** Both the 7B and
  14B produced generic tutorial code and invented API names instead of the real
  symbols (`handle_*`, `ConfigManager`, `_PARAM_PARSERS`). The 14B got as far as
  *finding* the right files via search but still couldn't produce correct, in-style
  edits. The bottleneck is understanding this codebase's conventions, not raw
  parameter count.
- **DeepSeek-V2-lite cannot do agent mode at all** (no `tools` capability in Ollama).

Nothing was applied to the project — the tree was clean after every run. The cloud
baseline proves the *tasks* are well-formed and solvable.

## 4. Comparison

Full table with measured/estimated labels: **[comparison.md](comparison.md)**.
Headline:

| | Cloud | 7B (measured) | 14B (measured) | Autocomplete 1.5B (measured) |
|---|---|---|---|---|
| Feature gen (Task A) | ✅ clean, first try | ❌ hallucinated (0/7) | ❌ same (0/7) | n/a |
| Agent mode (Task B) | ✅ 4/4 unaided | ❌ 0/4, no edits | ❌ 0/4, wrong files | n/a |
| Tab completion | n/a | n/a | n/a | ✅ works, instant, file-aware |
| Offline / private / free | no / no / no | yes / yes / yes | yes / yes / yes | yes / yes / yes |

## 5. Recommendation — "what is enough local"

- **Enough local:** **autocomplete** — the measured win (1.5B FIM: instant,
  single-file-aware, no reasoning needed). Plus anything that must stay **offline
  or private**, accepting lower quality. On this project, local *chat* could not be
  relied on for correct feature code even with files attached.
- **Cloud indispensable:** feature generation to the house style (cloud 6/6, both
  locals 0/7), **agentic / multi-file** work (cloud 4/4, locals 0/4),
  **project-context reasoning**, and the **harness** (profiles, subagents, FSM).
  The local model is a *code generator* at best, not a *harness*.
- **Best local combo (M4 Pro / 24 GB):** `qwen2.5-coder:1.5b-base` for autocomplete
  (the win). For chat, the **14B bought no quality over the 7B here**, so prefer the
  **7B** (faster, lighter, same outcome); use the 14B only for its marginally better
  agent-mode file discovery. temperature 0.1 / top_p 0.9 / num_ctx 8192. Not for
  agent mode — keep the cloud for that.

## 6. Honesty note

Per the project's no-fabricated-results rule: the **cloud, 7B, 14B, and
autocomplete** results are measured and dated 2026-07-26. Only the raw tok/s
**speed** rows are hardware-derived estimates, labelled `[E]` in
[comparison.md](comparison.md) — a planning aid, not observed benchmarks.
DeepSeek-V2-lite was not run (justified in the report). Nothing was applied to the
codebase; the cloud baseline is preserved as a diff, not merged as source.
