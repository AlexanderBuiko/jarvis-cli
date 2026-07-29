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

## Overfitting — the lecture's warning, observed

```
Iter  1: Val loss 6.791
Iter 50: Val loss 0.124   <- best
Iter100: Val loss 0.352   <- rose again
Train loss -> 0.000 by iter 80 (memorised)
```

Val loss bottomed at iter 50 then climbed while train loss hit zero: the model
started memorising after ~iter 50. The iter-100 adapter still scored 85% because
argmax stays right on 13 tiny-eval items even as the model gets overconfident,
but the **iter-50 checkpoint is the safer generaliser**. Follow-ups: re-tune with
`--iters 50` (or `--save-every 25` and pick the lowest-val-loss adapter), and
grow the eval set for a less noisy signal.

## Takeaway

Local LoRA fixed exactly what Day 7 could not: the **wrong prior**. Day-7 showed
self-checking cannot repair a confidently-wrong base model (20–40% accuracy);
fine-tuning changes the prior itself → 85%. Cloud-free, private, on a laptop.
The `mlx_eval_{base,tuned}.{json,md}` files hold the per-case detail.
