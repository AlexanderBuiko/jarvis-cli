"""Run the two-tier pipeline over simple / borderline / complex requests and measure it.

Answers the assignment's "measure" list: how many requests the micro-model
handled, how many fell back, the total big-LLM calls, and the average latency.
The micro-model is fit on the Day-6 train split; the test cases are the Day-7
buckets — ``correct`` (simple, reference-labelled), ``borderline``, ``noisy``
(complex) — 25 requests in all.

Local (default):  python -m microfirst.run
Fine-tuned fallback: python -m microfirst.run --model jarvis-classifier
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from confidence.testsets import Case, all_cases
from jarvis.indexing.embeddings import make_embedder

from .micro import MicroClassifier
from .pipeline import route

_FT = Path(__file__).resolve().parent.parent / "finetune" / "data"
_DATA = Path(__file__).parent / "data"
_BUCKET_LABEL = {"correct": "simple", "borderline": "borderline", "noisy": "complex"}


def load_train(path: Path) -> list[tuple[str, str]]:
    """Read ``(user_content, label)`` pairs the micro-model is fit on."""
    pairs: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        msgs = {m["role"]: m["content"] for m in json.loads(line)["messages"]}
        pairs.append((msgs["user"], msgs["assistant"].strip()))
    return pairs


def _build_engine(cloud: bool, model: str | None) -> tuple[object, str]:
    if cloud:
        from jarvis.openrouter.client import OpenRouterClient
        return OpenRouterClient(), (model or "openai/gpt-4o-mini")
    from jarvis.ollama.client import OllamaClient
    return OllamaClient(), (model or "qwen2.5:7b")


def run(cases: list[Case], micro: MicroClassifier, engine, model: str, temperature: float) -> dict:
    rows: list[dict] = []
    for c in cases:
        r = route(micro, engine, model, c.user_content, temperature, reference=c.reference)
        rows.append({
            "name": c.name, "bucket": _BUCKET_LABEL.get(c.bucket, c.bucket), "reference": c.reference,
            "tier": r.tier, "micro_label": r.micro.label, "micro_status": r.micro.status,
            "top_sim": r.micro.top_sim, "margin": r.micro.margin, "final_label": r.label,
            "escalated": r.escalated, "n_llm_calls": r.n_llm_calls,
            "latency_ms": round(r.latency_ms, 1), "cost_usd": r.cost_usd,
            "micro_correct": (r.reference is not None and r.micro.label == r.reference),
            "final_correct": (r.reference is not None and r.label == r.reference),
        })
    return {
        "fallback_model": model, "embedder": f"{micro.embedder.provider}/{micro.embedder.model}",
        "sim_floor": micro.sim_floor, "margin_floor": micro.margin_floor,
        "summary": _summary(rows), "by_bucket": _by_bucket(rows), "rows": rows,
    }


def _summary(rows: list[dict]) -> dict:
    n = len(rows)
    micro = [r for r in rows if r["tier"] == "micro"]
    fell = [r for r in rows if r["escalated"]]
    labelled = [r for r in rows if r["reference"] is not None]
    return {
        "n": n,
        "micro_handled": len(micro),
        "micro_handled_pct": round(len(micro) / n, 3) if n else None,
        "fell_back": len(fell),
        "total_llm_calls": sum(r["n_llm_calls"] for r in rows),
        "avg_latency_ms": round(statistics.mean(r["latency_ms"] for r in rows), 1) if n else None,
        "avg_latency_micro_ms": round(statistics.mean([r["latency_ms"] for r in micro]), 1) if micro else None,
        "avg_latency_fallback_ms": round(statistics.mean([r["latency_ms"] for r in fell]), 1) if fell else None,
        # Accuracy on the reference-labelled (simple) bucket: micro alone vs the two-tier result.
        "micro_accuracy": _acc(labelled, "micro_correct"),
        "twotier_accuracy": _acc(labelled, "final_correct"),
        "total_cost_usd": round(sum(r["cost_usd"] for r in rows if r["cost_usd"] is not None), 6) or None,
    }


def _acc(rows: list[dict], key: str) -> float | None:
    return round(sum(1 for r in rows if r[key]) / len(rows), 3) if rows else None


def _by_bucket(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for bucket in ("simple", "borderline", "complex"):
        b = [r for r in rows if r["bucket"] == bucket]
        if not b:
            continue
        micro = [r for r in b if r["tier"] == "micro"]
        out[bucket] = {
            "n": len(b), "micro_handled": len(micro), "fell_back": len(b) - len(micro),
            "avg_latency_ms": round(statistics.mean(r["latency_ms"] for r in b), 1),
        }
    return out


def _markdown(report: dict) -> str:
    s, bb = report["summary"], report["by_bucket"]
    lines = [
        f"# Micro-model first — {report['embedder']} → {report['fallback_model']}", "",
        f"Thresholds: sim_floor={report['sim_floor']}, margin_floor={report['margin_floor']}. "
        f"{s['n']} requests.", "",
        f"- **Micro-model handled {s['micro_handled']}/{s['n']} "
        f"({(s['micro_handled_pct'] or 0):.0%}) with no LLM call**; {s['fell_back']} fell back.",
        f"- Big-LLM calls: **{s['total_llm_calls']}** (vs {s['n']} if every request hit the LLM).",
        f"- Avg latency {s['avg_latency_ms']}ms overall — "
        f"micro path {s['avg_latency_micro_ms']}ms, fallback path {s['avg_latency_fallback_ms']}ms.",
        f"- Accuracy on the simple (labelled) bucket: micro-only "
        f"{_pct(s['micro_accuracy'])} → two-tier {_pct(s['twotier_accuracy'])}.",
        "",
        "| bucket | n | micro handled | fell back | avg latency |",
        "|---|---|---|---|---|",
    ]
    for bucket, m in bb.items():
        lines.append(f"| {bucket} | {m['n']} | {m['micro_handled']} | {m['fell_back']} | {m['avg_latency_ms']}ms |")
    lines += ["", "| request | bucket | micro label | status | top_sim | margin | tier | final |",
              "|---|---|---|---|---|---|---|---|"]
    for r in report["rows"]:
        served = "**llm**" if r["escalated"] else "micro"
        lines.append(
            f"| {r['name']} | {r['bucket']} | `{r['micro_label']}` | {r['micro_status']} | "
            f"{r['top_sim']} | {r['margin']} | {served} | `{r['final_label']}` |")
    lines += ["", "The micro-model is an embedding nearest-centroid classifier — no text generation. "
              "It escalates only when UNSURE (top similarity or margin below the floor)."]
    return "\n".join(lines) + "\n"


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.0%}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Two-tier micro-model-first inference.")
    parser.add_argument("--cloud", action="store_true", help="use OpenRouter for the LLM fallback")
    parser.add_argument("--model", default=None, help="fallback LLM model id (default qwen2.5:7b)")
    parser.add_argument("--sim-floor", type=float, default=0.6, help="min top similarity to accept (else UNSURE)")
    parser.add_argument("--margin-floor", type=float, default=0.02, help="min lead over runner-up to accept")
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args(argv)

    train_path = _FT / "train.jsonl"
    if not train_path.exists():
        print("error: finetune/data/train.jsonl not found — run the Day-6 split first", file=sys.stderr)
        return 2
    cases = all_cases(50)  # all held-out eval rows + borderline + noisy
    if not cases:
        print("error: no test cases (finetune/data/eval.jsonl missing?)", file=sys.stderr)
        return 2

    try:
        embedder = make_embedder()
        micro = MicroClassifier(embedder, sim_floor=args.sim_floor, margin_floor=args.margin_floor)
        micro.fit(load_train(train_path))
        engine, model = _build_engine(args.cloud, args.model)
    except Exception as exc:  # noqa: BLE001 — missing key / unreachable daemon
        print(f"error: setup failed: {exc}", file=sys.stderr)
        return 2

    try:
        report = run(cases, micro, engine, model, args.temperature)
    except Exception as exc:  # noqa: BLE001 — surface API/network failure cleanly
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _DATA.mkdir(parents=True, exist_ok=True)
    (_DATA / "microfirst_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (_DATA / "microfirst_results.md").write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report))
    print(f"wrote {_DATA / 'microfirst_results.json'} and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
