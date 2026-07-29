# confidence — inference confidence & acceptance control (Day 7)

Wraps the Day-6 message-priority classifier with a layer that decides **whether
to trust an answer**, without fine-tuning. A wrong label on an `urgent_now`
email is the unacceptable error this guards against.

Two mechanisms, fused into one verdict:

| Mechanism | How | Signal |
|---|---|---|
| **Redundancy** (self-consistency) | classify the same input `n` times at temperature > 0, vote the labels | agreement across runs |
| **Scoring** | each run also returns `confidence`; a format/allowed-value check gates malformed replies | mean confidence + validity |

### Verdict → acceptance

| Verdict | When | Action |
|---|---|---|
| **OK** | full agreement **and** mean confidence ≥ `conf_high` | accept automatically |
| **UNSURE** | a majority exists but agreement or confidence is soft | reject → human, or `--escalate` for another round |
| **FAIL** | no majority, all replies malformed, or confidence < `conf_low` | reject hard |

Only **OK** is accepted. `fuse()` in [assess.py](assess.py) is the pure policy;
thresholds live in `Config`.

## Run

```bash
python -m confidence.run              # OpenRouter (openai/gpt-4o-mini), default
python -m confidence.run --local      # local Ollama (qwen2.5:7b)
python -m confidence.run --escalate --n 3
```

Provider-agnostic over the project's `LLMEngine` seam — no OpenAI dependency.
Needs `OPENROUTER_API_KEY` (cloud) or a running Ollama (`--local`). Writes
`data/confidence_results.{json,md}`.

## Test buckets ([testsets.py](testsets.py))

- **correct** — clean inputs from `finetune/data/eval.jsonl` (reference labels → accuracy on what we accept).
- **borderline** — two labels genuinely compete; the layer should hesitate.
- **noisy** — garbled/truncated/contradictory; the layer should mostly reject.

## What it measures

Per bucket: rejection rate (UNSURE+FAIL), accuracy on accepted vs all,
re-inference calls from escalation, average latency, total cost. The story to
look for: near-100% acceptance on `correct`, high rejection on
`borderline`/`noisy`, and accepted-accuracy above raw accuracy — the gate works.

## Tests

`pytest tests/test_confidence.py` — drives the fusion policy and orchestration
through `FakeEngine`, no network.
