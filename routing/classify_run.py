"""Route the Day-6 message-priority task: cheap classifier first, escalate on doubt.

The general router (``routing.run``) answers open questions; this points the same
escalation idea at the Day-6 classifier and its **labelled** eval set — the
messages pulled from real mail. Because every case has a reference label, this
harness measures what the general demo cannot: whether escalating the uncertain
messages actually *fixes* the small model's mistakes, and at what extra cost.

Only one of the two heuristics applies here. A priority label is a single token —
it has no length and cannot "hedge" — so the length/hedge signal is meaningless;
the self-reported **confidence** is the whole gate. The classification primitive
is reused from the Day-7 confidence layer (``classify_scored`` → label + score).

Local (default):  python -m routing.classify_run
Cloud OpenRouter: python -m routing.classify_run --cloud
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from confidence.classify import ScoredRun, classify_scored
from confidence.testsets import Case, load_correct
from jarvis.llm.accounting import make_call_record

from .runtime import build_tiers

_DATA = Path(__file__).parent / "data"


def _should_escalate(run: ScoredRun, conf_low: float) -> tuple[bool, str]:
    """Confidence-only gate: a bad or unsure cheap label routes to the strong tier."""
    if run.label is None:
        return True, "cheap_error" if run.error is not None else "cheap_unparseable"
    if run.confidence is None:
        return True, "no_confidence"
    if run.confidence < conf_low:
        return True, f"low_confidence<{conf_low}"
    return False, ""


def _cost(run: ScoredRun, engine) -> float | None:
    return make_call_record(0, "routing", run.completion, engine)["cost"]["total_usd"]


def run(cases: list[Case], tiers, conf_low: float, temperature: float) -> dict:
    rows: list[dict] = []
    for c in cases:
        cheap = classify_scored(tiers.cheap.engine, tiers.cheap.model, c.user_content, temperature)
        escalate, reason = _should_escalate(cheap, conf_low)
        runs = [(cheap, tiers.cheap.engine)]
        strong: ScoredRun | None = None
        if escalate:
            strong = classify_scored(tiers.strong.engine, tiers.strong.model, c.user_content, temperature)
            runs.append((strong, tiers.strong.engine))
        final = strong if strong is not None else cheap
        costs = [_cost(r, e) for r, e in runs]
        known = [x for x in costs if x is not None]
        rows.append({
            "name": c.name, "reference": c.reference,
            "cheap_label": cheap.label, "cheap_confidence": cheap.confidence,
            "escalated": escalate, "reason": reason,
            "strong_label": strong.label if strong is not None else None,
            "served_by": "strong" if escalate else "cheap",
            "final_label": final.label,
            "cheap_correct": cheap.label == c.reference,
            "final_correct": final.label == c.reference,
            "n_calls": len(runs),
            "latency_ms": round(sum(r.completion.latency_ms for r, _ in runs), 1),
            "cost_usd": sum(known) if known else None,
        })
    return {
        "cheap_model": tiers.cheap.model, "strong_model": tiers.strong.model,
        "conf_low": conf_low, "temperature": temperature,
        "summary": _summary(rows), "rows": rows,
    }


def _summary(rows: list[dict]) -> dict:
    n = len(rows)
    esc = [r for r in rows if r["escalated"]]
    cheap_correct = sum(1 for r in rows if r["cheap_correct"])
    final_correct = sum(1 for r in rows if r["final_correct"])
    # Escalation earns its cost only where it turns a wrong cheap answer right.
    fixed = sum(1 for r in esc if not r["cheap_correct"] and r["final_correct"])
    broke = sum(1 for r in esc if r["cheap_correct"] and not r["final_correct"])
    total_calls = sum(r["n_calls"] for r in rows)
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    return {
        "n": n,
        "cheap_only_accuracy": round(cheap_correct / n, 3) if n else None,
        "routed_accuracy": round(final_correct / n, 3) if n else None,
        "escalated": len(esc),
        "escalation_rate": round(len(esc) / n, 3) if n else None,
        "mistakes_fixed_by_escalation": fixed,
        "made_worse_by_escalation": broke,
        "total_calls": total_calls,
        "extra_calls_from_escalation": total_calls - n,
        "avg_latency_ms": round(statistics.mean(r["latency_ms"] for r in rows), 1) if n else None,
        "total_cost_usd": round(sum(costs), 6) if costs else None,
    }


def _markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# Routing the Day-6 classifier — {report['cheap_model']} → {report['strong_model']}", "",
        f"conf_low={report['conf_low']}, temperature={report['temperature']}, {s['n']} labelled mail cases.", "",
        f"- **Cheap-only accuracy {s['cheap_only_accuracy']:.0%} → routed accuracy {s['routed_accuracy']:.0%}.**",
        f"- Escalated {s['escalated']}/{s['n']} ({s['escalation_rate']:.0%}); "
        f"of those, **{s['mistakes_fixed_by_escalation']} wrong cheap answers fixed**, "
        f"{s['made_worse_by_escalation']} made worse.",
        f"- Fallback cost: {s['extra_calls_from_escalation']} extra calls, "
        f"total spend {'$0.00 (local)' if not s['total_cost_usd'] else '$'+format(s['total_cost_usd'],'.4f')}.",
        "",
        "| case | reference | cheap (conf) | served by | final | cheap ok | final ok | reason |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report["rows"]:
        conf = "" if r["cheap_confidence"] is None else format(r["cheap_confidence"], ".2f")
        served = "**strong**" if r["escalated"] else "cheap"
        lines.append(
            f"| {r['name']} | `{r['reference']}` | `{r['cheap_label']}` ({conf}) | {served} | "
            f"`{r['final_label']}` | {'✅' if r['cheap_correct'] else '❌'} | "
            f"{'✅' if r['final_correct'] else '❌'} | {r['reason'] or '—'} |")
    lines += ["", "Only the confidence heuristic applies: a single-token label has no length and "
              "cannot hedge. A case escalates when the cheap label is unparseable/errored, or its "
              "self-reported confidence is below `conf_low`."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route the Day-6 classifier over its labelled eval set.")
    parser.add_argument("--cloud", action="store_true", help="use two OpenRouter models instead of local Ollama")
    parser.add_argument("--cheap-model", default=None, help="override the cheap tier model id")
    parser.add_argument("--strong-model", default=None, help="override the strong tier model id")
    parser.add_argument("--conf-low", type=float, default=0.6, help="escalate below this confidence")
    parser.add_argument("--temperature", type=float, default=0.0, help="0 = deterministic, reproducible routing")
    parser.add_argument("--limit", type=int, default=50, help="max eval cases")
    args = parser.parse_args(argv)

    cases = load_correct(args.limit)
    if not cases:
        print("error: finetune/data/eval.jsonl not found — run the Day-6 split first", file=sys.stderr)
        return 2
    try:
        tiers = build_tiers(local=not args.cloud, cheap_model=args.cheap_model,
                            strong_model=args.strong_model)
    except Exception as exc:  # noqa: BLE001 — missing key / unreachable daemon
        print(f"error: could not build tiers: {exc}", file=sys.stderr)
        return 2

    try:
        report = run(cases, tiers, args.conf_low, args.temperature)
    except Exception as exc:  # noqa: BLE001 — surface API/network failure cleanly
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _DATA.mkdir(parents=True, exist_ok=True)
    (_DATA / "routing_classify_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (_DATA / "routing_classify_results.md").write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report))
    print(f"wrote {_DATA / 'routing_classify_results.json'} and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
