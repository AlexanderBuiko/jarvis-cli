"""Score a local model on the eval set — base or LoRA-tuned — with MLX.

The local replacement for the OpenAI baseline: same accuracy/format criteria
(CRITERIA.md), but run on-device through ``mlx_lm``. Point it at the base model
for the "before" number, then add ``--adapter-path`` to score the tuned adapters
for "after". The two runs together are the deliverable's before/after.

Deterministic (greedy) so the comparison is stable. Needs ``mlx-lm`` installed
and downloads the base model on first use.

Base:   python -m finetune.mlx_eval
Tuned:  python -m finetune.mlx_eval --adapter-path finetune/mlx_adapters
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import LABELS

_DATA = Path(__file__).parent / "data"
_DEFAULT_MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"


def _label_from(text: str) -> str | None:
    """First known label appearing in the output, or None (constraint gate)."""
    stripped = text.strip()
    if stripped in LABELS:
        return stripped
    for label in LABELS:  # tolerate a stray word around the label
        if label in stripped:
            return label
    return None


def evaluate(model_id: str, adapter_path: str | None, eval_path: Path, limit: int) -> dict:
    from mlx_lm import generate, load  # local import: heavy, and optional dependency
    from mlx_lm.sample_utils import make_sampler

    model, tokenizer = load(model_id, adapter_path=adapter_path)
    sampler = make_sampler(temp=0.0)  # greedy → reproducible

    rows = [json.loads(ln) for ln in eval_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows = rows[:limit] if limit else rows
    results = []
    correct = clean = 0
    for obj in rows:
        prompt_msgs = [m for m in obj["messages"] if m["role"] != "assistant"]
        reference = obj["messages"][-1]["content"].strip()
        prompt = tokenizer.apply_chat_template(prompt_msgs, add_generation_prompt=True, tokenize=False)
        out = generate(model, tokenizer, prompt=prompt, max_tokens=8, sampler=sampler).strip()
        predicted = _label_from(out)
        is_correct = predicted == reference
        is_clean = out in LABELS
        correct += is_correct
        clean += is_clean
        results.append({"reference": reference, "raw": out, "predicted": predicted,
                        "correct": is_correct, "clean_format": is_clean})
    n = len(rows) or 1
    return {
        "model": model_id, "adapter_path": adapter_path, "count": len(rows),
        "accuracy": round(correct / n, 3), "format_clean": round(clean / n, 3),
        "results": results,
    }


def _markdown(report: dict) -> str:
    tag = "tuned" if report["adapter_path"] else "base"
    lines = [f"# Local eval ({tag}) — {report['model']}", "",
             f"- adapter: {report['adapter_path'] or '(none)'}",
             f"- examples: {report['count']}",
             f"- **accuracy: {report['accuracy']:.0%}**",
             f"- **format clean: {report['format_clean']:.0%}**", "",
             "| # | reference | predicted | raw | ok |", "|---|---|---|---|---|"]
    for i, r in enumerate(report["results"], 1):
        lines.append(f"| {i} | `{r['reference']}` | `{r['predicted']}` | `{r['raw'][:20]}` | "
                     f"{'✅' if r['correct'] else '❌'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a local model on the eval set.")
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument("--adapter-path", default=None, help="LoRA adapters (omit for base model)")
    parser.add_argument("--eval", type=Path, default=_DATA / "eval.jsonl")
    parser.add_argument("--limit", type=int, default=0, help="0 = whole eval set")
    args = parser.parse_args(argv)

    if not args.eval.exists():
        print(f"error: {args.eval} not found — run the Day-6 split first", file=sys.stderr)
        return 2
    try:
        report = evaluate(args.model, args.adapter_path, args.eval, args.limit)
    except Exception as exc:  # noqa: BLE001 — missing mlx-lm / model download failure
        print(f"error: {exc}", file=sys.stderr)
        return 1

    tag = "tuned" if args.adapter_path else "base"
    (_DATA / f"mlx_eval_{tag}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (_DATA / f"mlx_eval_{tag}.md").write_text(_markdown(report), encoding="utf-8")
    print(f"{tag}: accuracy={report['accuracy']:.0%}, format_clean={report['format_clean']:.0%} "
          f"over {report['count']} examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
