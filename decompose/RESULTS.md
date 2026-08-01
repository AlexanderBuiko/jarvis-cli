# Decomposition results — one big request vs a three-stage pipeline

Task: the Day-6 message-priority classifier over **65 labelled mail cases**
(train + eval), local models, temperature 0 (reproducible). Both options produce
the same deliverable (features + label + action + reason); the reported number is
label accuracy.

## The A/B, across three model configurations

| configuration | A · monolithic | B · multi-stage | B vs A (fixed / broke) |
|---|---|---|---|
| **all `qwen2.5:3b` (weak)** | 23% | **31%** | +9 / −4 → **net +5** |
| all `qwen2.5:7b` (strong) | **52%** | 49% | +14 / −16 → net −2 |
| extract 3b · **decide 7b** | 23% | 23% | +6 / −6 → net 0 |

B spends 3 short calls per case (195 total) to A's 1 big call (65). All local, $0.

## What it shows

**1. Decomposition helps the weak model: 23% → 31%.** Forcing the 3b to do
extraction, a conditional decision and generation in one big request overloads it.
Splitting the work into three narrow, strict-format stages — each doing one thing
with one allowed output shape — recovers real accuracy (fixed 9 cases, broke 4).
This is the assignment's thesis, confirmed on a model weak enough to show it.

**2. On the strong model the benefit disappears: 52% vs 49%.** The 7b already
handles the whole job in one call, so decomposition's gain (less load per call)
has little left to give, and the extra stages add a little variance. Decomposition
buys the most exactly where a single query is worst.

**3. The bottleneck is Stage 1 (extraction), and strict stages made that
visible.** Pointing *only* the decide stage at the 7b (`--decide-model`) does
nothing (23% → 23%): a stronger decider deciding from **wrong features** stays
wrong. Inspecting the stages shows why — the 3b extracts features like
`marketing, action_required=yes, importance=high` for a promotional email that
should be `ignore`, and any decider maps those to `urgent_now`. The only
configuration that jumps (all-7b, 52%) is the one that upgrades *extraction* too.
A monolithic call hides this; decomposition localises the failure to a stage.

## A caveat the build surfaced — strict formats are format-sensitive

The first 7b run collapsed to 5%. The cause was not the model but the **prompt**:
the analysis template showed the enum as the JSON value
(`"sender": "person|automated|marketing"`), and the 7b — being more literal about
following the schema — echoed `"sender": "automated|marketing"` verbatim, which the
strict parser correctly rejected. The 3b was too terse to copy the list, so it
looked fine. Rewriting the prompt to list allowed values in prose plus two concrete
examples fixed conformance to 10/10. The lesson: a strict-format pipeline is only
as good as each stage's format compliance, and a "smarter" model can comply *less*
with a sloppy schema — worth watching when you swap models between stages.

## Closing the loop — a fine-tuned decide stage (Day 6 → Day 9)

Everything above runs on base models. The real point of decomposition is that one
stage can be swapped for a model **specially fine-tuned for it** — here the Day-6
LoRA, exported to Ollama as `jarvis-classifier`. Pointing *only* Stage 2 at it
(`--tuned-decide jarvis-classifier`), scored on the **held-out 13 eval cases** (the
tuned model was trained on `train.jsonl`, so we never score it there):

| pipeline (13 held-out eval) | accuracy | Stage-2 fixed / broke vs mono |
|---|---|---|
| A · monolithic, base 3b | 23% | — |
| B · multi-stage, all base 3b | 31% | +2 / −1 |
| **B · multi-stage, fine-tuned decide** | **77%** | **+8 / −1** |

One specialised stage lifts the pipeline from 31% to 77% while Stage 1 (analyze)
and Stage 3 (generate) stay cheap, untuned 3b. That is the assignment's real
thesis made concrete: **strengthen the pipe pointwise — fine-tune the stage that
needs it, leave the ones that don't.** The "extraction is the bottleneck" finding
told us *which* stage carries the decision; a tuned classifier there both has the
right prior and reads the message directly, so it does not inherit the base
extraction errors.

Because the Day-6 adapter was trained on *raw message → label*, the tuned decide
stage classifies the message (its native input); Stage-1 features still feed
generation. A fine-tune trained on *features → label* would let the tuned model
consume Stage 1's output instead — the next pointwise step. (The exported q4_K_M
model scores 77% vs the MLX adapter's 85%; the gap is the re-quantisation — base 7b
is 38% either way. Export recipe in the README.)

## Takeaway

Two levers, and they compose. **Decomposition** is the diagnostic and prompt-
structure lever: it helps a weak model by splitting an overloaded request, and its
strict per-stage formats make each stage inspectable so you can *find* the weak one.
**Fine-tuning a single stage** is the fix: once decomposition localises the
decision as the stage that matters, tuning exactly that stage — and nothing else —
moves the pipeline from 31% to 77%. Decompose to locate, fine-tune pointwise to
fix; the other stages stay cheap and untouched.

## Reproduce

```bash
python -m decompose.run                            # all-3b, train+eval
python -m decompose.run --model qwen2.5:7b          # all-7b
python -m decompose.run --decide-model qwen2.5:7b     # 3b extract, base-7b decide
# Fine-tuned decide stage (build jarvis-classifier first — see README):
python -m decompose.run --eval-only                 # base baseline on the held-out set
python -m decompose.run --eval-only --tuned-decide jarvis-classifier
```
