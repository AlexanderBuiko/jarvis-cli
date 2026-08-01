# Micro-model-first results — embedding gate → LLM fallback

25 requests: 13 **simple** (reference-labelled, held-out eval), 6 **borderline**,
6 **complex** (noisy). The micro-model (`nomic-embed-text` nearest-centroid, fit on
the 52 Day-6 train messages) answers first; the big LLM runs only on `UNSURE`.
Thresholds `sim_floor=0.6, margin_floor=0.02`.

## How much the micro-model absorbed

| bucket | n | micro handled | fell back to LLM |
|---|---|---|---|
| simple | 13 | 9 | 4 |
| borderline | 6 | 4 | 2 |
| complex | 6 | 4 | 2 |
| **total** | **25** | **17 (68%)** | **8** |

- **68% of requests never reached the LLM.** Big-LLM calls dropped from 25 (naive,
  one per request) to **8**.
- **Latency: 21 ms on the micro path vs ~250–770 ms on the fallback path** — the
  handled requests are answered ~30× faster and at $0 (an embedding, then dot
  products, no generation).

## The fallback must beat the micro-model — or escalation hurts

Accuracy on the 13 labelled (simple) requests, micro-only vs the two-tier result,
for two fallback models:

| fallback model | micro-only | two-tier | effect of escalating |
|---|---|---|---|
| base `qwen2.5:7b` (38% on this task) | 77% | **62%** | **−15 pts — the fallback is worse than the micro** |
| fine-tuned `jarvis-classifier` (Day 9) | 77% | **77%** | held the line |

The micro-model is already ~77% on clean messages — *better* than the base 7B. So
routing its uncertain cases to the base 7B actively lowers accuracy: you escalate
to a weaker model. Only when the fallback is the **fine-tuned** classifier does the
two-tier system keep its accuracy. Efficiency (68% handled, 30× faster) then comes
at no accuracy cost.

## An honest weakness — the embedding gate is overconfident on garbage

Only 2 of 6 complex/noisy inputs fell back; the other 4 got a confident micro
label (e.g. a garbled string → `urgent_now`, `OK`). `nomic-embed-text` still places
junk at 0.65–0.78 similarity to *some* centroid, so `sim_floor=0.6` does not catch
it — the margin gate does most of the work. Raising `sim_floor` (≈0.72) sends more
noise to the fallback but also costs some simple-bucket coverage. This is the
nearest-centroid classifier's limit: it measures *closest class*, not *is this even
in-domain*, so a competent fallback (above) is what actually protects quality.

## Takeaway (the week's thread)

Micro-model-first is the cheap-path lever: a lightweight classifier — here an
embedding centroid model *fit on your own labelled data* — absorbs the easy
majority so the expensive model is spared. It composes with the earlier days: the
micro-model is trained on the Day-6 data, its `UNSURE` gate is the Day-7 confidence
idea, and its fallback should be the Day-9 **fine-tuned** model, not a generic big
LLM. Different tasks, different models, wired into one flow — cheap first, fine-
tuned only where it earns its cost.

## Reproduce

```bash
python -m microfirst.run                           # base 7b fallback
python -m microfirst.run --model jarvis-classifier    # fine-tuned fallback
```
