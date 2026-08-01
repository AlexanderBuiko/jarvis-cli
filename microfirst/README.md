# microfirst — micro-model first (Day 10)

Put a cheap **micro-model** in front of the big LLM. Most requests are easy and
never need a 7B generation; a tiny embedding classifier answers them, and only the
uncertain ones fall back to the big model. Task: the Day-6 message-priority
classification (a decision / enum task that reaches for an LLM by reflex).

Standalone assignment tooling, outside the `jarvis` package, built over its
`Embedder` and `LLMEngine` seams. Reuses `finetune.common` (labels, layout), the
Day-6 train split (to fit the micro-model) and the Day-7 test buckets.

## Tier 1 — the micro-model (mandatory)

An **embedding nearest-centroid classifier** — deliberately not an LLM:

1. embed the labelled training messages once (`nomic-embed-text`, ~137M params);
2. average each class into a centroid;
3. classify a new message by cosine similarity to those centroids — one embedding
   call plus a few dot products, **no text generation**.

It returns a structured label **and** a confidence status, gated on two signals:

| signal | what it catches | UNSURE when |
|---|---|---|
| **top similarity** | off-distribution input (far from every class) | `< sim_floor` |
| **margin** (top − runner-up) | borderline input (two classes tie) | `< margin_floor` |

`OK` needs both to clear their floor; otherwise `UNSURE`.

## Tier 2 — the LLM fallback

The big model runs **only** when the micro-model is `UNSURE`. (A malformed micro
answer would be the brief's third trigger, but the embedding classifier always
returns a valid label, so UNSURE is the only gate.)

**The fallback must be *better* than the micro-model**, or escalation hurts. The
base `qwen2.5:7b` scores 38% on this task — worse than the micro's ~77% — so
sending uncertain cases to it *lowers* accuracy. Point `--model` at the Day-9
fine-tuned classifier instead (`jarvis-classifier`, see `decompose/README.md`) and
the two-tier accuracy holds. That is the mentor's point: the micro-model is a tiny
classifier trained on your data; the fallback is the model you *fine-tuned* for the
job.

## Run

```bash
ollama serve
ollama pull nomic-embed-text && ollama pull qwen2.5:7b
python -m microfirst.run                          # base 7b fallback
python -m microfirst.run --model jarvis-classifier   # fine-tuned fallback (recommended)
python -m microfirst.run --sim-floor 0.7 --margin-floor 0.03   # stricter micro
python -m microfirst.run --cloud                  # OpenRouter LLM fallback
```

Writes `data/microfirst_results.{json,md}` — the routing split, big-LLM call count
and latency. Those outputs are git-ignored (derived from real mail); the committed
findings live in [RESULTS.md](RESULTS.md).

## Files

| File | What |
|---|---|
| `micro.py` | Tier 1 — the embedding nearest-centroid classifier (`fit` / `classify`, OK/UNSURE) |
| `pipeline.py` | the two-tier `route`: micro first, LLM only on UNSURE |
| `run.py` | the harness → `data/microfirst_results.{json,md}` |

Tests: `tests/test_microfirst.py` — the classifier and route driven offline with
`FakeEmbedder` + `FakeEngine`, no network.
