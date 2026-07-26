# Week 6 — Local LLMs

**Source:** `transcriptions/06-local-llm-summary.md`,
`transcriptions/06-local-llm-notes.txt`
**Theme:** Run the same kind of models as the cloud, but on your own device —
free, private, offline.

## Why local, not cloud

| Problem (cloud) | Detail |
|---|---|
| Expensive | ~$200/mo subscriptions; hardware pays back in a couple of years |
| No privacy | Your data leaves for a server by definition |
| Internet-dependent | WiFi down → no coding |
| Cost grows with use | More usage, more you pay |

Local: pay once for hardware, scale for free.

## How an LLM works (recap)

```
Query → [Input Layer] → [Hidden Layers × N] → [Output Layer] → Answer
                              ↑ self-attention / transformers
```

- **Forward propagation** — prediction (guess next words).
- **Backward propagation** — training (user corrects → weights adjust).
- **Weights** = numeric strength of a connection; **node** = one neuron;
  **layer** = neurons at one level; **parameters** = all weights (7B = 7 billion).

## Parameters and memory

| Size | VRAM (fp16) | Hardware |
|---|---|---|
| 1B | ~2 GB | any laptop CPU |
| 3B | ~6 GB | weak GPU |
| 7B | ~14 GB | decent discrete GPU |
| 13B | ~26 GB | RTX 3090/4090 |
| 70B | ~140 GB | Mac Studio / cluster |

Formula: **params × 2 bytes (fp16) = VRAM in GB**.

## Quantisation — the key trick

Lower weight precision to save memory:

```
float16 (2 B) → INT8 (1 B)   → 2× smaller
float16 (2 B) → INT4 (0.5 B) → 4× smaller
```

70B example: fp16 = 140 GB (impossible at home), Q4 ≈ 35 GB (one Mac Studio),
Q8 ≈ 70 GB (minimal quality loss). Model-name tags: `Q4_K_M`, `Q8_0`, `IQ3_XS`.
Rule: **Q4–Q6** is a good balance; below Q4 quality visibly degrades.

## Local vs cloud

| | Local | Cloud |
|---|---|---|
| Speed | slower | faster |
| Quality | lower (7B ≈ GPT-3.5) | higher |
| Cost | one-off (hardware) | monthly |
| Privacy | full | none |
| Internet | not needed | needed |

For simple internal tasks, a 7B model is enough.

## Tools

- **Ollama** ⭐ — simple CLI + HTTP API (used in the course).
- **LM Studio** — GUI, good for beginners.
- **llama.cpp** — max control, low-level.
- **MLX** — for Apple Silicon Macs.
- Mobile: 1–3B models via llama.cpp (offline anywhere).

## RAG + local LLM

```
Documents → Embedding → Vector DB
                            ↓
Query → Search → Context + LLM → Answer
```

Why it is a must-have: fixes stale knowledge (open-source models lag 3–12 mo),
lowers hallucinations (answer tied to concrete docs), extends knowledge without
fine-tuning.

## Maps to jarvis-cli

- `jarvis/ollama/OllamaClient` sits behind the `LLMEngine` seam.
- Live cloud↔local main toggle: `config set provider`, via `RoutingEngine`.
- Optional per-role local pins (utility / sub-agent); invariant check-local /
  resolve-main. See `project_local_llm_engine` memory (model `qwen2.5:7b`).

## Week's assignment

Install and run a local LLM (Ollama + Qwen); compare local vs cloud on the same
prompts; apply MCP + RAG to the local model; (bonus) a toggle that switches
local↔cloud and labels which produced each result.
