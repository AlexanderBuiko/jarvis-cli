"""Measure the un-tuned baseline on 10 held-out eval examples.

Step 5. Runs the first 10 rows of ``eval.jsonl`` through the base model
(``gpt-4o-mini``, no fine-tune) using the exact system+user turns from the
dataset, records each prediction next to the reference, and reports the two
criteria from CRITERIA.md: accuracy (exact label match) and format (fraction of
outputs that are a clean bare label). This frozen number is what the fine-tuned
model has to beat.

Runs through **OpenRouter by default** — the project's own provider — which
serves ``openai/gpt-4o-mini`` over an OpenAI-compatible endpoint. Pass
``--provider openai`` to hit OpenAI directly instead. Either way it is pure
inference; the fine-tuning *job* still runs on OpenAI (see upload_client).

Reads the provider's key from the environment. Costs a few cents per run.

Run:  python -m finetune.baseline
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

from .common import LABELS

_DATA = Path(__file__).parent / "data"
_TIMEOUT = 30

# Provider presets. The default model differs because OpenRouter namespaces the
# same model as ``openai/gpt-4o-mini`` while OpenAI calls it ``gpt-4o-mini``.
_PROVIDERS = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "model": "openai/gpt-4o-mini",
        "extra_headers": {"HTTP-Referer": "https://github.com/jarvis-cli", "X-Title": "Jarvis CLI"},
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "key_env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
        "extra_headers": {},
    },
}


def classify(messages: list[dict], model: str, provider: dict, api_key: str) -> str:
    """One chat completion via the given provider; return raw assistant text."""
    resp = requests.post(
        provider["url"],
        headers={"Authorization": f"Bearer {api_key}", **provider["extra_headers"]},
        json={"model": model, "messages": messages, "temperature": 0, "max_tokens": 10},
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"].strip()


def _is_clean_label(text: str) -> bool:
    """True if the output is exactly one known label, nothing else."""
    return text.strip() in LABELS


def run(eval_path: Path, model: str, limit: int, provider: dict, api_key: str) -> dict:
    rows = [json.loads(line) for line in eval_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = rows[:limit]
    results = []
    correct = clean = 0
    for obj in rows:
        prompt = [m for m in obj["messages"] if m["role"] != "assistant"]
        reference = obj["messages"][-1]["content"].strip()
        prediction = classify(prompt, model, provider, api_key)
        norm = prediction.strip().strip(".").lower()
        is_correct = norm == reference
        is_clean = _is_clean_label(prediction)
        correct += is_correct
        clean += is_clean
        results.append({
            "user": next(m["content"] for m in prompt if m["role"] == "user"),
            "reference": reference,
            "prediction": prediction,
            "correct": is_correct,
            "clean_format": is_clean,
        })
    n = len(rows) or 1
    return {
        "model": model,
        "count": len(rows),
        "accuracy": round(correct / n, 3),
        "format_clean": round(clean / n, 3),
        "results": results,
    }


def _write_markdown(report: dict, path: Path) -> None:
    lines = [
        f"# Baseline — {report['model']} (no fine-tune)",
        "",
        f"- Examples: {report['count']}",
        f"- **Accuracy: {report['accuracy']:.0%}** (exact label match)",
        f"- **Format clean: {report['format_clean']:.0%}** (bare label, no prose)",
        "",
        "| # | reference | prediction | correct | clean |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(report["results"], 1):
        lines.append(f"| {i} | `{r['reference']}` | `{r['prediction']}` | "
                     f"{'✅' if r['correct'] else '❌'} | {'✅' if r['clean_format'] else '❌'} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Baseline on the un-tuned model.")
    parser.add_argument("--eval", type=Path, default=_DATA / "eval.jsonl")
    parser.add_argument("--provider", choices=list(_PROVIDERS), default="openrouter",
                        help="inference provider (default openrouter)")
    parser.add_argument("--model", default=None,
                        help="override model id (default: the provider's gpt-4o-mini id)")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)

    provider = _PROVIDERS[args.provider]
    model = args.model or provider["model"]
    api_key = os.environ.get(provider["key_env"])
    if not api_key:
        print(f"error: set {provider['key_env']}", file=sys.stderr)
        return 2
    if not args.eval.exists():
        print(f"error: {args.eval} not found — run split first", file=sys.stderr)
        return 2

    try:
        report = run(args.eval, model, args.limit, provider, api_key)
    except Exception as exc:  # noqa: BLE001 — surface API/network failure cleanly
        print(f"error: {exc}", file=sys.stderr)
        return 1

    (_DATA / "baseline_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(report, _DATA / "baseline_results.md")
    print(f"baseline [{args.provider}:{model}]: accuracy={report['accuracy']:.0%}, "
          f"format_clean={report['format_clean']:.0%} over {report['count']} examples")
    print(f"wrote {_DATA / 'baseline_results.json'} and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
