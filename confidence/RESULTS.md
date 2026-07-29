# Day-7 results — confidence assessment (cloud vs local)

`python -m confidence.run --escalate` and `--local`. n=3 redundancy samples,
temperature 0.6, conf_high 0.75, conf_low 0.40, escalation on UNSURE. 22 cases
each. Per-case message content is in the git-ignored `data/confidence_results*.json`;
only aggregates/labels are here.

## Cloud — openai/gpt-4o-mini (OpenRouter)

| Bucket | n | OK | UNSURE | FAIL | Reject % | acc(all) | acc(accepted) | Re-inference | Avg latency | Cost |
|---|---|---|---|---|---|---|---|---|---|---|
| correct | 10 | 10 | 0 | 0 | 0% | 20% | 20% | +0 | 4.8s | $0.00129 |
| borderline | 6 | 4 | 0 | 2 | 33% | — | — | +6 (2 escalated) | 6.1s | $0.00067 |
| noisy | 6 | 5 | 0 | 1 | 17% | — | — | +0 (3 filtered) | 4.4s | $0.00040 |

Total 72 calls, **$0.0024**.

## Local — qwen2.5:7b (Ollama, free, private)

| Bucket | n | OK | UNSURE | FAIL | Reject % | acc(all) | acc(accepted) | Re-inference | Avg latency | Cost |
|---|---|---|---|---|---|---|---|---|---|---|
| correct | 10 | 9 | 1 | 0 | 10% | 40% | **44%** | +3 | 2.1s | $0.00 |
| borderline | 6 | 3 | 3 | 0 | 50% | — | — | +9 | 2.0s | $0.00 |
| noisy | 6 | 4 | 2 | 0 | 33% | — | — | +6 | 1.8s | $0.00 |

Total 84 calls, **$0.00**, run in ~45s.

## Cloud vs local

| | gpt-4o-mini | qwen2.5:7b |
|---|---|---|
| accuracy (correct) | 20% | **40%** |
| acc(accepted) | 20% — no lift | **44% — gate removed a wrong case** |
| contradictory input | Azure content filter → 400 refusal | handled → UNSURE (runs disagreed) |
| cost / latency | $0.0024 / 4.8s per case | $0.00 / 2.1s per case |

## The key finding

**The confidence layer's usefulness depends on model calibration.**

- On **gpt-4o-mini** the correct bucket got 3/3 agreement at 0.85–0.95 confidence
  on *every* case, yet was right only 20% — a strong, wrong "ignore" prior. All 8
  wrong answers were accepted; **acc(accepted) == acc(all) == 20%, zero lift.**
  Self-consistency and self-scoring track *conviction*, not *correctness*, and
  cannot see a systematic wrong prior.
- On **qwen2.5:7b** the same mechanism *did* help: its runs disagree on hard
  cases (better calibration), so it rejected one wrong `correct` case and lifted
  accepted accuracy **40% → 44%**, and rejected more borderline/noisy inputs.
- **Redundancy beat scoring** on the contradictory input locally: per-run
  confidence was 1.0, but the three runs disagreed → UNSURE. Self-consistency
  caught what self-scoring alone would have accepted.

## Conclusion

Redundancy + self-scoring reliably reject genuine ambiguity and provider
refusals at ~3× cost (up to 6× when escalating), but they cannot repair a
confidently-wrong prior — they only help a model whose uncertainty is
calibrated. The local qwen model was more accurate, better calibrated, free,
faster and free of the content filter that refused a legitimate input — the
concrete case for the local-first mandate. To fix the residual correct-bucket
errors you still need an **independent** signal: the Day-6 fine-tuned model,
which changes the prior itself.
