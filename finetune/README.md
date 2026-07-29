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
| 6. Fine-tune (cloud) | `python -m finetune.upload_client --go` | uploads + launches job |

Steps 5 and 6 hit the OpenAI API and cost money; step 6 without `--go` is a dry
run. Step 1 hits Gmail. All three are yours to launch.

## Local fine-tune (OpenAI blocked — UPD)

Since OpenAI is blocked, the cloud `upload_client` cannot run. The local
replacement is **LoRA on a small model with MLX** (Apple Silicon; Unsloth is
NVIDIA-only). `mlx-lm` is an *optional* tool — install it only for this path:

```bash
pip install mlx-lm
python -m finetune.mlx_prepare                       # data/ -> mlx_data/{train,valid,test}.jsonl
python -m finetune.mlx_eval                           # BEFORE: base model accuracy
mlx_lm.lora --model mlx-community/Qwen2.5-7B-Instruct-4bit \
    --train --data finetune/mlx_data \
    --fine-tune-type lora --mask-prompt \
    --num-layers 8 --batch-size 4 --iters 100 --learning-rate 1e-4 \
    --adapter-path finetune/mlx_adapters
python -m finetune.mlx_eval --adapter-path finetune/mlx_adapters   # AFTER: tuned accuracy
```

Notes:
- `--mask-prompt` trains on the label only, not the prompt — right for classification.
- 4-bit base = QLoRA in spirit (the lecture's Q-LoRA), and fits a Mac's RAM.
- The dataset is tiny (52 train), so keep `--iters` low and watch the validation
  loss — the lecture's overfitting warning applies. Bump iters only if val loss
  is still falling.
- `mlx_eval` writes `data/mlx_eval_{base,tuned}.{json,md}`; the pair is the
  before/after. To serve the tuned model through the REPL, `mlx_lm.fuse` then
  export to GGUF for Ollama.

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
