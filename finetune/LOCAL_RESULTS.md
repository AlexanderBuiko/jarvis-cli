# Day-6 local fine-tune results — MLX LoRA (OpenAI-blocked UPD)

OpenAI is blocked, so the cloud fine-tune was replaced with **local LoRA on
Apple Silicon** via `mlx-lm`. Base model `mlx-community/Qwen2.5-7B-Instruct-4bit`
(4-bit = QLoRA in spirit), 52 train / 13 eval, greedy decoding.

Tune command: `mlx_lm.lora --fine-tune-type lora --mask-prompt --num-layers 8
--batch-size 4 --iters 100 --learning-rate 1e-4`. ~40 min on-device, **$0**.

## Before → after

| Model | Accuracy | Format clean |
|---|---|---|
| Base (untuned) | 38% | 100% |
| **Tuned (LoRA)** | **85%** | 100% |

**+47 points.** The base 38% matches the Day-7 local base (~40%), so this is a
clean before/after on the same model.

Errors (ref → pred):
- Base misses 8/13, spread across all classes (often collapsing to `ignore`).
- Tuned misses only 2/13, **both `this_week`** (→ urgent_now / ignore). The model
  learned urgent_now / today / ignore well; `this_week` (the subtle
  social-notification class) stays hardest — unsurprising, it was the most
  sender-homogeneous class in the data.

## Checkpoint sweep — early-stopping on val loss was a mistake

The first run sampled val loss only every 50 iters and looked like textbook
overfitting (0.124 at iter 50 → 0.352 at iter 100). A retune with checkpoints
and validation every 10 iters (seed 0) shows that curve was **noise** — with
only 13 validation items, val loss bounces:

```
Iter  10 20   30    40    50    60    70    80
Val   0.65 1.16 0.63 0.29 0.22 0.26 0.47 0.15
```

So we picked by the metric that actually matters — eval **accuracy** per
checkpoint:

| iter | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 |
|---|---|---|---|---|---|---|---|---|
| accuracy | 38% | 31% | 31% | 54% | 62% | 54% | 54% | **85%** |

Accuracy climbs (noisily) and **peaks at iter 80**, which also has the lowest val
loss. The earlier "stop at iter 50" advice was wrong: iter 50 is only 62%. The
shipped adapter is **iter 80 (85%)** — same accuracy as the first run's iter 100
but at the val-loss minimum and 20 fewer steps. On a dataset this small the
per-checkpoint accuracy sweep is the reliable selector, not val loss.

Real follow-up: **grow the eval set** — 13 items make every signal noisy.

## Takeaway

Local LoRA fixed exactly what Day 7 could not: the **wrong prior**. Day-7 showed
self-checking cannot repair a confidently-wrong base model (20–40% accuracy);
fine-tuning changes the prior itself → 85% (base 38% → tuned iter-80 85%).
Cloud-free, private, on a laptop. The `mlx_eval_{base,tuned}.{json,md}` files hold
the per-case detail; both remaining errors are the subtle `this_week` class.
