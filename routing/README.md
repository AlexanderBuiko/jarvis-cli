# routing — model escalation router

Request routing between two models: a cheap/fast model answers first; if the
answer looks uncertain, the query is re-routed to a stronger model and that answer
is served instead. **Confident answers stay on the cheap model, so the fast path
is the common path.**

Standalone assignment tooling — outside the `jarvis` package, built over its
`LLMEngine` seam. Run the harness as a module.

## The two heuristics

The brief asks for at least one uncertainty heuristic; this uses both it names,
fused with the confidence score as primary and length as a corroborator.

| Heuristic | Signal | Role in the decision |
|---|---|---|
| **Confidence score** | the model self-rates 0..1 how sure it is (returned in the same JSON as the answer) | primary — below `conf_low`, escalate |
| **Response length / hedging** | word count of the answer, and explicit hedge words ("I'm not sure", "it depends") | corroborator — in the middle band, a short or hedged answer escalates; at high confidence, hedging contradicts the score and escalates |

## The rule (`router.decide`, pure and unit-tested)

```
confidence < conf_low                       → escalate (clearly unsure)
conf_low ≤ confidence < conf_high           → escalate iff hedged OR shorter than min_words
confidence ≥ conf_high                       → keep, unless the text hedges (self-contradiction) → escalate
no usable confidence / unparseable / error  → escalate
```

Self-score first, length second, on purpose: raw length alone is a poor signal —
a correct "4" to "2+2" is short and certain — so length only counts once the
score is already lukewarm. A cheap call that *fails* (content filter, unreachable
daemon) escalates too: the strong tier is the fallback, and one bad query never
aborts the batch.

## Model tiers

Default is **two local Ollama models** — a small-parameter model escalating to a
bigger one, $0 and private, no OpenAI:

| Tier | Default model | Size |
|---|---|---|
| cheap (tried first) | `qwen2.5:3b` | 1.9 GB |
| strong (escalation) | `qwen2.5:7b` | 4.7 GB |

Both run through one `OllamaClient`; the per-call `model` tag picks the size.
Override with `--cheap-model` / `--strong-model`. `--cloud` routes between two
OpenRouter models instead (`openai/gpt-4o-mini` → `anthropic/claude-3.5-sonnet`;
still no OpenAI dependency — the ids are served through OpenRouter).

## Run

```bash
ollama serve            # if not already running
ollama pull qwen2.5:3b  # cheap tier
ollama pull qwen2.5:7b  # strong tier
python -m routing.run                       # general queries, local, default thresholds
python -m routing.run --conf-low 0.6 --conf-high 0.85
python -m routing.run --cloud               # two OpenRouter models
python -m routing.classify_run              # route the Day-6 classifier over its mail eval set
```

Writes `data/routing_results.{json,md}` — the per-query split (which stayed small,
which went big, and why) plus the fallback cost (extra calls, latency, spend).
Those outputs are git-ignored; the committed findings live in [RESULTS.md](RESULTS.md).

## Files

| File | What |
|---|---|
| `runtime.py` | `build_tiers()` — the cheap/strong `Tier` pair, local or cloud |
| `answer.py` | one answer call → `{answer, confidence}`, defensive parse, error-tolerant |
| `heuristics.py` | the pure length signals: `word_count`, `is_hedged` |
| `router.py` | `Config`, `decide()` (pure policy), `route()` (orchestration + fallback + accounting) |
| `queries.py` | the easy/hard query series the router is tested on |
| `run.py` | the general-query harness → `data/routing_results.{json,md}` |
| `classify_run.py` | routes the **Day-6 classifier** over its labelled mail eval set (confidence gate only; measures whether escalation fixes mistakes) → `data/routing_classify_results.{json,md}` |

Tests: `tests/test_routing.py` — `decide()` and `route()` driven offline with
`FakeEngine`, no network.
