"""Run the router over the query series and report the split.

Answers the assignment's "test on a series of queries": which queries stayed on
the small model, which went to the big one, and why — plus the cost of the
fallback (extra calls, latency, spend). Writes a JSON record and a Markdown
summary to ``data/``.

Local (default):  python -m routing.run
Cloud OpenRouter: python -m routing.run --cloud
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from .queries import Query, all_queries
from .router import Config, route
from .runtime import build_tiers

_DATA = Path(__file__).parent / "data"


def run(queries: list[Query], tiers, cfg: Config) -> dict:
    rows: list[dict] = []
    for q in queries:
        r = route(tiers, q.text, cfg)
        rows.append({
            "name": q.name, "bucket": q.bucket, "expected": q.expected,
            "served_by": r.served_by, "escalated": r.escalated, "reasons": r.reasons,
            "cheap_confidence": r.cheap_confidence,
            "words": r.signals.get("words"), "hedged": r.signals.get("hedged"),
            "final_confidence": r.final_confidence,
            "n_calls": r.n_calls, "latency_ms": round(r.latency_ms, 1), "cost_usd": r.cost_usd,
            "final_answer": (r.final_answer or "")[:200],
        })
    return {
        "cheap_model": tiers.cheap.model, "strong_model": tiers.strong.model,
        "config": vars(cfg), "summary": _summary(rows), "rows": rows,
    }


def _summary(rows: list[dict]) -> dict:
    n = len(rows)
    escalated = [r for r in rows if r["escalated"]]
    kept = [r for r in rows if not r["escalated"]]
    # Did the router's split match the intuitive expectation?
    agree = sum(1 for r in rows if r["served_by"] == r["expected"])
    total_calls = sum(r["n_calls"] for r in rows)
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    return {
        "n": n,
        "kept_on_cheap": len(kept),
        "escalated_to_strong": len(escalated),
        "escalation_rate": round(len(escalated) / n, 3) if n else None,
        "matched_expectation": f"{agree}/{n}",
        "total_calls": total_calls,
        "extra_calls_from_escalation": total_calls - n,  # one baseline call per query
        "avg_calls_per_query": round(total_calls / n, 2) if n else None,
        "avg_latency_ms": round(statistics.mean(r["latency_ms"] for r in rows), 1) if n else None,
        "total_cost_usd": round(sum(costs), 6) if costs else None,
    }


def _markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# Model escalation router — {report['cheap_model']} → {report['strong_model']}", "",
        f"Config: {report['config']}", "",
        f"- **{s['kept_on_cheap']}/{s['n']} stayed on the cheap model**, "
        f"{s['escalated_to_strong']}/{s['n']} escalated to the strong model "
        f"(escalation rate {s['escalation_rate']:.0%}).",
        f"- Router split matched intuition on **{s['matched_expectation']}** queries.",
        f"- Fallback cost: {s['extra_calls_from_escalation']} extra calls "
        f"({s['avg_calls_per_query']} avg per query), "
        f"total spend {'$0.00 (local)' if not s['total_cost_usd'] else '$'+format(s['total_cost_usd'],'.4f')}.",
        "",
        "| query | bucket | expected | served by | conf | words | hedged | reasons |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report["rows"]:
        conf = "" if r["cheap_confidence"] is None else format(r["cheap_confidence"], ".2f")
        served = "**strong**" if r["escalated"] else "cheap"
        lines.append(
            f"| {r['name']} | {r['bucket']} | {r['expected']} | {served} | {conf} | "
            f"{r['words']} | {'yes' if r['hedged'] else '—'} | {', '.join(r['reasons']) or '—'} |")
    lines += ["", "`conf` / `words` / `hedged` are the cheap-tier signals the policy read. "
              "A query escalates when the confidence score is low, or is lukewarm and a length "
              "signal corroborates, or the text hedges despite a high score."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route a query series and report the split.")
    parser.add_argument("--cloud", action="store_true", help="use two OpenRouter models instead of local Ollama")
    parser.add_argument("--cheap-model", default=None, help="override the cheap tier model id")
    parser.add_argument("--strong-model", default=None, help="override the strong tier model id")
    parser.add_argument("--conf-low", type=float, default=0.6, help="escalate below this confidence")
    parser.add_argument("--conf-high", type=float, default=0.85, help="keep at/above this confidence")
    args = parser.parse_args(argv)

    try:
        tiers = build_tiers(local=not args.cloud, cheap_model=args.cheap_model,
                            strong_model=args.strong_model)
    except Exception as exc:  # noqa: BLE001 — missing key / unreachable daemon
        print(f"error: could not build tiers: {exc}", file=sys.stderr)
        return 2

    cfg = Config(conf_low=args.conf_low, conf_high=args.conf_high)
    try:
        report = run(all_queries(), tiers, cfg)
    except Exception as exc:  # noqa: BLE001 — surface API/network failure cleanly
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _DATA.mkdir(parents=True, exist_ok=True)
    (_DATA / "routing_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (_DATA / "routing_results.md").write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report))
    print(f"wrote {_DATA / 'routing_results.json'} and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
