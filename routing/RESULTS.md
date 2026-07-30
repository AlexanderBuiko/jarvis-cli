# Routing results — qwen2.5:3b → qwen2.5:7b (local, $0)

12 queries, 6 easy and 6 hard, routed cheap-first with escalation on doubt.
Deterministic (temperature 0), so the split is reproducible. Config:
`conf_low=0.6, conf_high=0.85, min_words=4`.

## The split — which stayed small, which went big

| query | bucket | served by | conf | words | hedged | why it escalated |
|---|---|---|---|---|---|---|
| capital-france | easy | cheap | 1.00 | 1 | — | — |
| arithmetic | easy | cheap | 1.00 | 1 | — | — |
| week-days | easy | cheap | 1.00 | 6 | — | — |
| json-define | easy | cheap | 0.95 | 6 | — | — |
| water-boil | easy | cheap | 0.99 | 1 | — | — |
| greeting | easy | cheap | 0.95 | 2 | — | — |
| bat-and-ball | hard | cheap | 0.95 | 4 | — | — |
| word-problem | hard | cheap | 0.90 | 4 | — | — |
| **ambiguous** | hard | **strong** | 0.80 | 9 | yes | hedged in the middle band |
| **niche-fact** | hard | **strong** | 0.50 | 15 | — | confidence below 0.6 |
| tradeoffs | hard | cheap | 0.90 | 47 | — | — |
| code-edgecase | hard | cheap | 0.95 | 41 | — | — |

**10/12 stayed on the cheap model; 2/12 escalated** (escalation rate 17%). The
fast path handled every easy query on one call. The fallback cost is exactly the
2 extra calls for the 2 escalations — `$0.00` on local models.

Each heuristic earned its place: **confidence** caught `niche-fact` (the model
honestly rated an obscure 1936 attendance figure 0.50), and **hedging** caught
`ambiguous` ("Is it better?"), which the model rated a fairly high 0.80 but
answered with "it depends" — the length signal overrode the score.

## The honest finding — a small model is overconfident

Confidence-only routing under-escalates because **qwen2.5:3b's self-scores cluster
near 1.0**. The clearest case is `bat-and-ball`: the classic trap where the
intuitive-but-wrong answer is $0.10 (correct is $0.05). The 3b model gives the
wrong answer *and* rates it 0.95, so it stays on the cheap tier — a confidently
wrong answer that no self-report can flag. `word-problem` is the same shape.

This is exactly the Day-7 ceiling restated for routing: **self-checking cannot
detect what the model doesn't know it got wrong.** Two consequences shaped the
design:

1. The confidence band sits high (0.6 / 0.85), not at a textbook 0.5 / 0.75 —
   otherwise nothing would ever escalate. The thresholds were calibrated to where
   *this* model separates sure from unsure, and that boundary is model-specific.
2. Length/hedging is a genuine second signal, not decoration: it caught a case
   (`ambiguous`, self-rated 0.80) that the confidence floor alone would have kept.

What confidence-only routing cannot fix — the confidently-wrong reasoning traps —
is precisely what the Day-6 fine-tune addressed by changing the model's prior. The
three days line up: **fine-tuning fixes the wrong prior, confidence control rejects
what the model knows it's unsure of, and routing escalates that same doubt to a
stronger model — but none of them catches a confident mistake.**

`tradeoffs` and `code-edgecase` staying on the cheap tier is arguably correct, not
a miss: the 3b model produced long, reasonable answers it was rightly confident in.
The router is meant to save the strong model for genuine doubt, and it did.

## Routing the Day-6 classifier — where uncertainty routing breaks

The same router pointed at the Day-6 message-priority task and its **labelled**
mail eval set (`routing.classify_run`) is the sharper test: with ground-truth
labels we can ask whether escalation actually *fixes* mistakes. It does not — and
the reason is instructive.

- **Cheap-only 38% → routed 38%. Zero of 13 escalated.** The 3b model labels the
  messages wrong 8 times out of 13, and rates almost every wrong label **0.90–1.00**.
  The confidence gate never fires, so nothing is routed to the strong model.
- The confidence heuristic that worked on general-knowledge queries fails here
  because the small model is not merely wrong — it is **confidently wrong on a task
  it was never trained for**.

The obvious next idea is a heuristic that ignores the self-report: **self-consistency**
(sample the cheap model N times; disagreement = uncertainty, the Day-7 redundancy
signal). Probed on these 13 cases it also fails — the model agrees with itself at
**1.00 on every case, including all 8 it gets wrong**. The errors are not just
confident, they are *stable*.

**Takeaway.** Uncertainty-based routing only works when the cheap model can
recognise its own limits. On a task it is systematically bad at, no self-signal —
self-report or self-consistency — surfaces the errors, so there is nothing to
escalate on. The fixes are then *not* routing heuristics: fine-tune the cheap model
(Day-6 did exactly this, 38% → 85%), or route by **task type** a priori (send all
priority-classification to the strong/fine-tuned model, keep the cheap model for
the general Q&A it is actually calibrated on). This is the honest boundary of the
"if unsure, escalate" strategy — it needs a model that knows when it is unsure.

## Reproduce

```bash
python -m routing.run            # general queries → data/routing_results.{json,md}
python -m routing.classify_run   # Day-6 mail eval → data/routing_classify_results.{json,md}
```
