"""Run the confidence layer over all three buckets and report the metrics.

Answers the assignment's "measure" list: how many responses were rejected, how
much re-inference cost, and the impact on latency and cost. Writes a JSON record
and a Markdown summary to ``data/``.

Cloud (default):  python -m confidence.run
Local Ollama:     python -m confidence.run --local
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from .assess import Config, assess
from .runtime import build_engine
from .testsets import Case, all_cases

_DATA = Path(__file__).parent / "data"


def _bucket_metrics(rows: list[dict]) -> dict:
    """Aggregate one bucket's per-case rows into the reported numbers."""
    n = len(rows)
    verdicts = Counter(r["verdict"] for r in rows)
    rejected = verdicts["UNSURE"] + verdicts["FAIL"]
    total_calls = sum(r["n_calls"] for r in rows)
    errored_calls = sum(r["n_errors"] for r in rows)
    # Baseline redundancy is n samples per case; anything beyond is escalation.
    escalation_extra = total_calls - sum(r["base_calls"] for r in rows)
    latencies = [r["latency_ms"] for r in rows]
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    accepted = [r for r in rows if r["verdict"] == "OK"]
    with_ref = [r for r in rows if r["reference"] is not None]
    acc_all = _accuracy([r for r in with_ref]) if with_ref else None
    acc_accepted = _accuracy([r for r in accepted if r["reference"] is not None]) if with_ref else None
    return {
        "n": n,
        "verdicts": dict(verdicts),
        "rejected": rejected,
        "rejection_rate": round(rejected / n, 3) if n else None,
        "accuracy_all": acc_all,
        "accuracy_accepted": acc_accepted,
        "total_calls": total_calls,
        "errored_calls": errored_calls,
        "escalation_extra_calls": escalation_extra,
        "avg_calls_per_case": round(total_calls / n, 2) if n else None,
        "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "total_cost_usd": round(sum(costs), 6) if costs else None,
    }


def _accuracy(rows: list[dict]) -> float | None:
    scored = [r for r in rows if r["reference"] is not None]
    if not scored:
        return None
    correct = sum(1 for r in scored if r["label"] == r["reference"])
    return round(correct / len(scored), 3)


def run(cases: list[Case], engine, model: str, cfg: Config) -> dict:
    rows: list[dict] = []
    for case in cases:
        a = assess(engine, model, case.user_content, cfg)
        rows.append({
            "name": case.name, "bucket": case.bucket, "reference": case.reference,
            "verdict": a.verdict, "label": a.label, "agreement": round(a.agreement, 3),
            "mean_confidence": a.mean_confidence, "n_calls": a.n_calls, "n_errors": a.n_errors,
            "base_calls": cfg.n, "escalated": a.escalated,
            "latency_ms": round(a.latency_ms, 1), "cost_usd": a.cost_usd,
        })
    buckets = ["correct", "borderline", "noisy"]
    return {
        "model": model,
        "config": vars(cfg),
        "by_bucket": {b: _bucket_metrics([r for r in rows if r["bucket"] == b])
                      for b in buckets if any(r["bucket"] == b for r in rows)},
        "rows": rows,
    }


def _markdown(report: dict) -> str:
    lines = [f"# Confidence layer — {report['model']}", "",
             f"Config: {report['config']}", "",
             "| bucket | n | OK | UNSURE | FAIL | reject % | acc(all) | acc(accepted) | calls | escalated | avg latency |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for b, m in report["by_bucket"].items():
        v = m["verdicts"]
        lines.append(
            f"| {b} | {m['n']} | {v.get('OK',0)} | {v.get('UNSURE',0)} | {v.get('FAIL',0)} | "
            f"{(m['rejection_rate'] or 0):.0%} | "
            f"{'' if m['accuracy_all'] is None else format(m['accuracy_all'],'.0%')} | "
            f"{'' if m['accuracy_accepted'] is None else format(m['accuracy_accepted'],'.0%')} | "
            f"{m['total_calls']} (+{m['escalation_extra_calls']}) | "
            f"{'yes' if m['escalation_extra_calls'] else '—'} | "
            f"{'' if m['avg_latency_ms'] is None else str(m['avg_latency_ms'])+'ms'} |")
    errored = ", ".join(f"{b}={m['errored_calls']}" for b, m in report["by_bucket"].items())
    lines += ["", "`calls` shows total inference calls and (+N) extra from re-inference on UNSURE.",
              f"Errored/filtered calls (counted as FAIL signal): {errored}.",
              "Only **OK** is accepted; UNSURE and FAIL are rejected."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the confidence layer and measure it.")
    parser.add_argument("--local", action="store_true", help="use local Ollama instead of OpenRouter")
    parser.add_argument("--model", default=None, help="override the model id")
    parser.add_argument("--n", type=int, default=3, help="redundancy samples per input")
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--escalate", action="store_true", help="re-sample on UNSURE")
    parser.add_argument("--limit", type=int, default=10, help="correct-bucket size")
    args = parser.parse_args(argv)

    cases = all_cases(args.limit)
    if not any(c.bucket == "correct" for c in cases):
        print("note: finetune/data/eval.jsonl not found — running borderline+noisy only", file=sys.stderr)
    if not cases:
        print("error: no cases to run", file=sys.stderr)
        return 2

    try:
        engine, model = build_engine(args.local, args.model)
    except Exception as exc:  # noqa: BLE001 — missing key / unreachable daemon
        print(f"error: could not build engine: {exc}", file=sys.stderr)
        return 2

    cfg = Config(n=args.n, temperature=args.temperature, escalate=args.escalate)
    try:
        report = run(cases, engine, model, cfg)
    except Exception as exc:  # noqa: BLE001 — surface API/network failure cleanly
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _DATA.mkdir(parents=True, exist_ok=True)
    (_DATA / "confidence_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (_DATA / "confidence_results.md").write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report))
    print(f"wrote {_DATA / 'confidence_results.json'} and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
