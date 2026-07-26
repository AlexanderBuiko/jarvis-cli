# Cloud vs local — code assistant comparison

Two tasks on jarvis-cli: **Task A** feature generation (add a REPL `models`
command) and **Task B** agent-mode multi-file change (add a `presence_penalty`
config param). Cloud = Claude Code; local = Ollama models in Continue (PyCharm),
M4 Pro / 24 GB. Full run notes in [results-raw.md](results-raw.md).

**Cell labels:**
- **[M] measured** — actually run and observed on 2026-07-26.
- **[E] estimated** — hardware-derived projection (mem bandwidth ≈ 273 GB/s, q4);
  used only for the raw tok/s speed rows, which were not stopwatched. A planning
  aid, not a benchmark.

Models actually run: **cloud**, **qwen2.5-coder:7b**, **qwen2.5-coder:14b**,
**qwen2.5-coder:1.5b-base** (autocomplete). **DeepSeek-V2 16B-lite was not run**
(no `tools` capability → no agent mode; a third chat-only model added nothing).

## The table

| Criterion | Cloud (Claude Code) | Qwen2.5-Coder 7B | Qwen2.5-Coder 14B | DeepSeek-V2 16B-lite |
|---|---|---|---|---|
| **Code quality** (house-style, Task A chat) | **[M]** 6/6 applicable ✓ | **[M]** 0/7 — hallucinated | **[M]** 0/7 — same as 7B | not run |
| **First try worked?** | **[M]** ✅ 469/469, ruff clean | **[M]** ❌ no usable output | **[M]** ❌ no usable output | not run |
| **Turns to correct** | **[M]** 0 | **[M]** abandoned | **[M]** abandoned | not run |
| **Speed — generation** | **[M]** fast, network-bound* | **[E]** ~30–45 tok/s | **[E]** ~15–22 tok/s | **[E]** ~45–60 tok/s (MoE) |
| **Speed — time to first token** | **[M]** ~1–3 s (network) | **[E]** <1 s | **[E]** ~1–2 s | **[E]** <1 s |
| **Project-context understanding** | **[M]** high — all points unaided | **[M]** none — invented APIs, never searched | **[M]** partial — search found real files, but wrong edits | not run |
| **Agent mode** (multi-file, plan→edit) | **[M]** full — Task B 4/4 | **[M]** failed — 0/4, no real edits | **[M]** failed — 0/4, edited wrong files | ❌ no `tools` cap — can't |
| **Works offline** | ❌ needs network | ✅ | ✅ | ✅ |
| **Marginal cost per call** | $ (API tokens) | free | free | free |
| **Privacy** (code leaves machine?) | leaves | stays local | stays local | stays local |
| **Max useful context** | very large | 8k set (32k capable) | 8k set (32k capable) | 8k set (128k capable) |
| **RAM while loaded** (q4) | n/a | **[E]** ~5–6 GB | **[E]** ~10–11 GB | **[E]** ~9–10 GB |

\* Cloud speed is network round-trips, not tokens/sec on the local GPU — not
directly comparable to the local tok/s cells. The cloud column is fully **[M]**;
the exact code it produced is in `submission/day4/cloud-baseline.diff` and is the
reference "good answer".

**The headline measured result:** on the two *coding* tasks, **neither local model
produced applyable, in-style code** — the 14B did not beat the 7B on quality. The
one difference the larger model made was in agent-mode *file discovery* (14B ran a
codebase search and surfaced the real `commands.py`/`loop.py`; the 7B never
grounded at all) — but it still invented a `validate_config` function, edited the
wrong files, and missed the real `_PARAM_PARSERS`/`_PARAM_VALIDATORS` pattern.

## Autocomplete (FIM — measured, and the local bright spot)

| | Qwen2.5-Coder 1.5B-base |
|---|---|
| Latency feel | **[M]** instant — usable at keystroke speed |
| Single-file context | **[M]** ✅ passed — completed in-file symbols, not generic guesses |
| Completion usefulness | **[M]** good for line/block completion within the current file |
| RAM | **[E]** ~1–2 GB (co-runs with a chat model easily) |

Autocomplete is single-file, FIM-based, needs no project reasoning or tool-driving
— exactly what a small model does well, and the only local feature that clearly
worked here.

## Findings observed during the runs (2026-07-26)

- **Autocomplete works well locally** (measured). Fast, and it grounds in the
  current file. This is the strongest local use case.
- **Chat feature-gen failed on both 7B and 14B** — both invented `main.py`,
  generic APIs and fake data, and ignored the attached real files. Bigger model,
  same result: the bottleneck is project grounding, not raw size.
- **Agent mode is a cloud strength.** Tools execute locally only with *System
  Message tools OFF* + `capabilities: [tool_use]`. Even then, the 7B failed to
  ground at all; the 14B searched and found real files but produced wrong edits
  in the wrong places. Cloud did Task B 4/4 unaided.
- **DeepSeek-V2 cannot do agent mode** (no `tools` capability in Ollama).
- Local is best judged in **Chat** mode; but on this project even chat needed the
  code handed to it and still produced non-applyable output.

## Recommendation — "what is enough local"

Grounded in the measured runs (cloud 6/6 + Task B 4/4; both local models 0/7 on
Task A and 0/4 on Task B; autocomplete measured working):

- **Local is enough for:** **tab autocomplete** — the clear, measured win
  (1.5B FIM model: instant, single-file-aware). Plus anything that must stay
  **offline or private**, where you accept lower quality for zero data egress.
  On this project, local chat could *not* be relied on for correct, in-style
  feature code even with the files attached.
- **Cloud is indispensable for:** **all real coding work here** — feature
  generation that follows the house style (cloud 6/6, both locals 0/7), anything
  **agentic or multi-file** (cloud 4/4, locals 0/4), **project-context reasoning**
  (cloud matched the existing `_active_provider_model` idiom unaided), and the
  **harness itself** — profiles, subagents, task FSM — which a single local model
  has no machinery to run. Restating the Day-1 finding: the local model is a
  *code generator* (at best), not a *harness*.
- **Best local combo on this box (M4 Pro / 24 GB):** `qwen2.5-coder:1.5b-base`
  for autocomplete (the win) at temperature 0.1. For chat, **the extra RAM/latency
  of the 14B bought no quality over the 7B here**, so if you run local chat at all,
  the 7B is the pragmatic pick (faster, lighter, same outcome); reach for the 14B
  only for its slightly better agent-mode file discovery. Params: temperature 0.1,
  top_p 0.9, num_ctx 8192. **Do not rely on any local model for agent mode — keep
  the cloud for that.**

### Day-1 note (carried over)
Only the **code-style slice** of the Day-1 rules went into the local system prompt
([system-prompt.md](system-prompt.md)); the harness half (profiles, subagents, FSM,
MCP) was dropped because an IDE chat/autocomplete model has no orchestration layer
to apply it to. That split is itself a finding — the local assistant uses a strict
subset of the rules.
