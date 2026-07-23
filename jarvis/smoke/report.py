"""
Render smoke results as one plain-text report.

Text, not HTML: the "screenshots" of a terminal interface *are* text, so a text
report shows them losslessly and diffs cleanly in a PR. Each step prints its
captured output verbatim — that block is the evidence the agent actually drove
the interface and saw the result, and it is where a human looks when a step fails.

Returns a string (the module never prints); the entrypoint or CI writes it.
"""

from __future__ import annotations

from .adapter import ScenarioResult

_RULE = "─" * 68


def render_report(results: list[ScenarioResult]) -> str:
    """A full report: a summary line, then each scenario with per-step captures."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    lines = [
        "SMOKE REPORT",
        _RULE,
        f"scenarios: {passed}/{total} passed",
        "",
    ]
    for r in results:
        lines += _render_scenario(r)
    if passed != total:
        lines += [_RULE, "", "WHERE IT BROKE", *_diagnose(results)]
    return "\n".join(lines)


def _render_scenario(r: ScenarioResult) -> list[str]:
    head = "PASS" if r.passed else "FAIL"
    out = [f"[{head}] {r.name}  ({r.platform})", _RULE]
    if r.error:
        out += [f"  adapter error: {r.error}", ""]
        return out
    for i, s in enumerate(r.steps, 1):
        mark = "ok " if s.passed else "XX "
        out.append(f"  {mark}step {i}: {s.action}")
        if s.expect is not None:
            out.append(f"      expect: {s.expect!r}  →  {'found' if s.passed else 'MISSING'}")
        for cap_line in (s.capture.splitlines() or ["(no output)"]):
            out.append(f"      | {cap_line}")
        if not s.passed:
            out.append(f"      ^^ {s.note}")
        out.append("")
    return out


def _diagnose(results: list[ScenarioResult]) -> list[str]:
    """Point at the first failure of each broken scenario — the likely cause."""
    out = []
    for r in results:
        if r.passed:
            continue
        if r.error:
            out.append(f"  - {r.name}: the interface itself failed ({r.error}). "
                      f"Check that `python -m jarvis` starts cleanly.")
            continue
        first = next((s for s in r.steps if not s.passed), None)
        if first:
            out.append(f"  - {r.name}: step {r.steps.index(first)+1} "
                      f"`{first.action}` — {first.note}. Its capture above shows "
                      f"what the interface actually returned.")
    return out
