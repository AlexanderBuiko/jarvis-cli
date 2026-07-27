# finetune — message-priority classifier dataset (Day 6)

Build a fine-tuning dataset that teaches a model to tag one incoming email with
one priority label: `urgent_now`, `today`, `this_week`, `ignore`. Task type:
**classification**. Label definitions and evaluation criteria live in
[CRITERIA.md](CRITERIA.md).

Standalone assignment tooling — outside the `jarvis` package, talks to the
OpenAI fine-tuning API directly. Run each step as a module.

## Pipeline

| Step | Command | Output |
|---|---|---|
| 1. Pull real inbox | `python -m finetune.extract_messages --count 50` | `data/review.json` (label blank) |
| 2. Curate | *edit `data/review.json` by hand* | keep rows you want, fill each `label` |
| 3a. Convert real | `python -m finetune.review_to_jsonl` | `data/real.jsonl` |
| 3b. Synthetic | *generated, modelled on your real rows* | `data/synthetic.jsonl` |
| 4. Split | `python -m finetune.split data/real.jsonl data/synthetic.jsonl` | `data/train.jsonl`, `data/eval.jsonl` |
| —. Validate | `python -m finetune.validate data/train.jsonl data/eval.jsonl` | pass/fail + label balance |
| 5. Baseline | `python -m finetune.baseline` | `data/baseline_results.{json,md}` |
| 6. Fine-tune | `python -m finetune.upload_client --go` | uploads + launches job |

Steps 5 and 6 hit the OpenAI API and cost money; step 6 without `--go` is a dry
run. Step 1 hits Gmail. All three are yours to launch.

## Environment

```bash
export JARVIS_IMAP_USER="you@gmail.com"
export JARVIS_IMAP_PASSWORD="<gmail app password>"   # not your normal password
export OPENROUTER_API_KEY="sk-or-..."   # baseline (default provider)
export OPENAI_API_KEY="sk-..."          # fine-tune job only (upload_client)
```

The baseline runs on **OpenRouter** by default (`openai/gpt-4o-mini`); pass
`--provider openai` to use OpenAI instead. The fine-tuning job in `upload_client`
is OpenAI-only — OpenRouter does not run fine-tunes.

Nothing is hardcoded; no secret is written to disk. `data/` is git-ignored by
default because it can hold real email — decide per file before committing.
