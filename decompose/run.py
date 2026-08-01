"""A/B the monolithic call against the multi-stage pipeline on the labelled mail set.

Answers the assignment: implement both options and show which solves the task
better. Runs each labelled message through Option A (one request) and Option B
(three requests) with the same base model, and reports label accuracy, calls,
latency and cost for each — plus the effect of pointing Stage 2 at a stronger
model (``--decide-model``).

Local (default):  python -m decompose.run
Bigger decide:    python -m decompose.run --decide-model qwen2.5:7b
Cloud OpenRouter: python -m decompose.run --cloud
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from .monolithic import run_monolithic
from .pipeline import run_multistage

_FT = Path(__file__).resolve().parent.parent / "finetune" / "data"
_DATA = Path(__file__).parent / "data"


@dataclass
class Case:
    name: str
    user_content: str
    reference: str


def load_cases(paths: list[Path], limit: int) -> list[Case]:
    """Read labelled classification rows (system/user/assistant) from JSONL files."""
    cases: list[Case] = []
    for path in paths:
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            obj = json.loads(line)
            msgs = {m["role"]: m["content"] for m in obj["messages"]}
            cases.append(Case(f"{path.stem}-{i}", msgs["user"], msgs["assistant"].strip()))
            if limit and len(cases) >= limit:
                return cases
    return cases


def _build_engine(cloud: bool, model: str | None) -> tuple[object, str]:
    if cloud:
        from jarvis.openrouter.client import OpenRouterClient
        return OpenRouterClient(), (model or "openai/gpt-4o-mini")
    from jarvis.ollama.client import OllamaClient
    return OllamaClient(), (model or "qwen2.5:3b")


def run(cases: list[Case], engine, models: dict[str, str], temperature: float,
        tuned_decide: str | None = None) -> dict:
    rows: list[dict] = []
    for c in cases:
        mono = run_monolithic(engine, models["analyze"], c.user_content, temperature)
        multi = run_multistage(engine, models, c.user_content, temperature, tuned_decide=tuned_decide)
        rows.append({
            "name": c.name, "reference": c.reference,
            "mono_label": mono.label, "mono_correct": mono.label == c.reference,
            "mono_calls": mono.n_calls, "mono_latency_ms": round(mono.latency_ms, 1),
            "mono_cost_usd": mono.cost_usd,
            "multi_label": multi.label, "multi_correct": multi.label == c.reference,
            "multi_calls": multi.n_calls, "multi_latency_ms": round(multi.latency_ms, 1),
            "multi_cost_usd": multi.cost_usd,
        })
    return {
        "base_model": models["analyze"], "decide_model": models["decide"],
        "tuned_decide": tuned_decide,
        "temperature": temperature, "summary": _summary(rows), "rows": rows,
    }


def _method(rows: list[dict], prefix: str) -> dict:
    n = len(rows)
    correct = sum(1 for r in rows if r[f"{prefix}_correct"])
    calls = sum(r[f"{prefix}_calls"] for r in rows)
    costs = [r[f"{prefix}_cost_usd"] for r in rows if r[f"{prefix}_cost_usd"] is not None]
    lat = [r[f"{prefix}_latency_ms"] for r in rows]
    return {
        "accuracy": round(correct / n, 3) if n else None,
        "correct": correct,
        "total_calls": calls,
        "avg_latency_ms": round(statistics.mean(lat), 1) if lat else None,
        "total_cost_usd": round(sum(costs), 6) if costs else None,
    }


def _summary(rows: list[dict]) -> dict:
    fixed = sum(1 for r in rows if not r["mono_correct"] and r["multi_correct"])
    broke = sum(1 for r in rows if r["mono_correct"] and not r["multi_correct"])
    return {
        "n": len(rows),
        "monolithic": _method(rows, "mono"),
        "multistage": _method(rows, "multi"),
        "multistage_fixed": fixed,   # wrong monolithic → right multi-stage
        "multistage_broke": broke,   # right monolithic → wrong multi-stage
    }


def _markdown(report: dict) -> str:
    s = report["summary"]
    a, b = s["monolithic"], s["multistage"]
    if report.get("tuned_decide"):
        mix = f" (decide on fine-tuned {report['tuned_decide']})"
    elif report["decide_model"] != report["base_model"]:
        mix = f" (decide on {report['decide_model']})"
    else:
        mix = ""
    lines = [
        f"# Inference decomposition — {report['base_model']}{mix}", "",
        f"{s['n']} labelled mail cases, temperature {report['temperature']}.", "",
        "| option | accuracy | correct | calls | avg latency | cost |",
        "|---|---|---|---|---|---|",
        f"| A · monolithic | **{a['accuracy']:.0%}** | {a['correct']}/{s['n']} | {a['total_calls']} | "
        f"{a['avg_latency_ms']}ms | {_money(a['total_cost_usd'])} |",
        f"| B · multi-stage | **{b['accuracy']:.0%}** | {b['correct']}/{s['n']} | {b['total_calls']} | "
        f"{b['avg_latency_ms']}ms | {_money(b['total_cost_usd'])} |",
        "",
        f"Multi-stage fixed **{s['multistage_fixed']}** cases the monolithic call got wrong, "
        f"and broke {s['multistage_broke']}.",
        "",
        "| case | reference | A mono | B multi | A ok | B ok |",
        "|---|---|---|---|---|---|",
    ]
    for r in report["rows"]:
        lines.append(
            f"| {r['name']} | `{r['reference']}` | `{r['mono_label']}` | `{r['multi_label']}` | "
            f"{'✅' if r['mono_correct'] else '❌'} | {'✅' if r['multi_correct'] else '❌'} |")
    lines += ["", "Multi-stage spends 3 short calls to the monolith's 1 big call. Each stage has a "
              "strict format (enum features → single label → compact result), so a stage can only "
              "fail loudly, never drift."]
    return "\n".join(lines) + "\n"


def _money(v: float | None) -> str:
    return "$0.00 (local)" if not v else f"${v:.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A/B monolithic vs multi-stage inference.")
    parser.add_argument("--cloud", action="store_true", help="use OpenRouter instead of local Ollama")
    parser.add_argument("--model", default=None, help="base model for all stages and the monolith")
    parser.add_argument("--decide-model", default=None, help="stronger base model for Stage 2 only")
    parser.add_argument("--tuned-decide", default=None,
                        help="fine-tuned model for Stage 2 (classifies the message directly); "
                             "use with --eval-only to avoid train leakage")
    parser.add_argument("--eval-only", action="store_true",
                        help="score on the held-out eval.jsonl only (required for --tuned-decide)")
    parser.add_argument("--temperature", type=float, default=0.0, help="0 = deterministic, reproducible")
    parser.add_argument("--limit", type=int, default=0, help="max cases (0 = all)")
    args = parser.parse_args(argv)

    if args.tuned_decide and not args.eval_only:
        print("error: --tuned-decide must be run with --eval-only — the fine-tuned model was "
              "trained on train.jsonl, so scoring it there would leak.", file=sys.stderr)
        return 2

    paths = [_FT / "eval.jsonl"] if args.eval_only else [_FT / "train.jsonl", _FT / "eval.jsonl"]
    cases = load_cases(paths, args.limit)
    if not cases:
        print("error: no labelled data — run the Day-6 split first (finetune/data/*.jsonl)", file=sys.stderr)
        return 2
    try:
        engine, base = _build_engine(args.cloud, args.model)
    except Exception as exc:  # noqa: BLE001 — missing key / unreachable daemon
        print(f"error: could not build engine: {exc}", file=sys.stderr)
        return 2

    models = {"analyze": base, "decide": args.decide_model or base, "generate": base}
    try:
        report = run(cases, engine, models, args.temperature, tuned_decide=args.tuned_decide)
    except Exception as exc:  # noqa: BLE001 — surface API/network failure cleanly
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _DATA.mkdir(parents=True, exist_ok=True)
    (_DATA / "decompose_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (_DATA / "decompose_results.md").write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report))
    print(f"wrote {_DATA / 'decompose_results.json'} and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
