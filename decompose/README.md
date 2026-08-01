# decompose — inference decomposition (Day 9)

Take a task a single query solves poorly and run it two ways: as **one big
request** (Option A) and as a **three-stage pipeline** (Option B). The task is the
Day-6 message-priority classifier — complex classification + multi-field
extraction + a conditional decision — which a small model handles badly in one
shot. The harness runs both options on the labelled mail set and compares them.

Standalone assignment tooling, outside the `jarvis` package, built over its
`LLMEngine` seam. Reuses `finetune.common` (label set, sanitisation, layout) and
the Day-6 labelled data.

## Option A — monolithic

One request → one JSON answer that does the whole job at once:

```json
{"sender": "...", "action_required": "...", "deadline": "...", "importance": "...",
 "label": "...", "action": "...", "why": "..."}
```

Cheap in calls (exactly one), but the model juggles extraction, a conditional
decision and generation together.

## Option B — multi-stage

The same job split into three short calls, **each with a strict format**:

| Stage | In → out | Format |
|---|---|---|
| 1. analyze / normalize | raw message → features | compact JSON, **enums only** (`sender`, `action_required`, `deadline`, `importance`) |
| 2. decide / classify | features → one label | a **single enum** token (`urgent_now` / `today` / `this_week` / `ignore`) |
| 3. generate | label + features → result | one-line reason; action from a fixed `label → action` table |

Stage 2 never sees the raw message — only the normalised features — so the
decision is a clean mapping over a tiny input. **Strictness is the point**: a
stage can only emit an allowed value, and its parser rejects anything else as a
loud failure (short-circuit) instead of passing free text downstream. That also
**localises failure** — you can see *which* stage was wrong, which a monolithic
call hides.

**Different models per stage.** All stages share one engine; the per-call model id
selects the model, so `--decide-model qwen2.5:7b` points only Stage 2 at a
stronger model while extraction and generation stay cheap.

**A *fine-tuned* decide stage.** `--tuned-decide jarvis-classifier` points Stage 2
at the Day-6 LoRA-tuned classifier (exported to Ollama, see below). Because that
model was trained on *raw message → label*, it classifies the message directly;
Stage-1 features still feed generation. On the held-out eval set this lifts the
pipeline from 31% (all base) to 77% while Stage 1 and Stage 3 stay cheap, untuned
3b — "strengthen the pipe pointwise". Must be run with `--eval-only` (the tuned
model was trained on `train.jsonl`, so scoring it there would leak). See
[RESULTS.md](RESULTS.md).

## Run

```bash
ollama serve
ollama pull qwen2.5:3b && ollama pull qwen2.5:7b
python -m decompose.run                          # A/B, all stages on qwen2.5:3b
python -m decompose.run --decide-model qwen2.5:7b   # Stage 2 on the bigger model
python -m decompose.run --model qwen2.5:7b        # everything on qwen2.5:7b
python -m decompose.run --cloud                   # OpenRouter (openai/gpt-4o-mini)
python -m decompose.run --eval-only --tuned-decide jarvis-classifier   # fine-tuned decide stage
```

Writes `data/decompose_results.{json,md}` — the A/B table plus a per-case
comparison. Those outputs are git-ignored (derived from real mail); the committed
findings live in [RESULTS.md](RESULTS.md).

## Export the fine-tuned decide stage

`--tuned-decide jarvis-classifier` needs the Day-6 LoRA served by Ollama. Fuse the
adapter into the base model, then import it (one-off, ~2 min, local, $0):

```bash
# 1. Fuse the LoRA adapter into the base model, dequantized to a safetensors dir.
mlx_lm.fuse \
  --model mlx-community/Qwen2.5-7B-Instruct-4bit \
  --adapter-path finetune/mlx_adapters \
  --save-path /path/to/jarvis-classifier-fused --dequantize

# 2. Import into Ollama, quantized to q4_K_M (~4.7 GB). The Modelfile FROM must
#    point at the fused dir from step 1.
ollama create jarvis-classifier --quantize q4_K_M -f decompose/jarvis-classifier.Modelfile
```

The [Modelfile](jarvis-classifier.Modelfile) sets a Qwen2.5 ChatML template so the
Day-6 system prompt is honoured per call. Sanity check: `jarvis-classifier` scores
~77% on the held-out eval vs base 7b's 38% (the MLX adapter itself is 85%; the gap
is the q4_K_M re-quantisation).

## Files

| File | What |
|---|---|
| `stages.py` | enums, `Features`/`Outcome` carriers, the three stage prompts, strict parsers, `ask`/`account` helpers |
| `monolithic.py` | Option A — one big request → full result |
| `pipeline.py` | Option B — analyze → decide → generate; `tuned_decide` swaps in the fine-tuned classifier |
| `run.py` | the A/B harness → `data/decompose_results.{json,md}` |
| `jarvis-classifier.Modelfile` | Ollama import recipe for the fine-tuned decide stage |

Tests: `tests/test_decompose.py` — the parsers and both paths driven offline with
`FakeEngine`, no network.
