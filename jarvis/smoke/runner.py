"""
The scenario runner — feeds one scenario's steps through an adapter.

Platform-agnostic on purpose: it holds no terminal, HTTP or mobile knowledge,
only the ``SmokeAdapter`` contract. A scenario is a plain dict (loaded from JSON,
the project's only persistence form), so authoring a new smoke path needs no
code — matching how ``scripts/run_scenario.py`` already drives the app from a
JSON file.

Scenario shape::

    {
      "name": "config round-trip",
      "platform": "cli",
      "steps": [
        {"action": "config set temperature 0.7", "expect": "temperature = 0.7"},
        {"action": "config show",                "expect": "temperature"}
      ]
    }

``expect`` is optional; a step with none just records its capture and passes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapter import ScenarioResult, SmokeAdapter, StepResult


def load_scenarios(path: str | Path) -> list[dict[str, Any]]:
    """Load one scenario file, or every ``*.json`` under a directory (sorted)."""
    p = Path(path)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def run_scenario(adapter: SmokeAdapter, scenario: dict[str, Any]) -> ScenarioResult:
    """Drive ``scenario`` through ``adapter`` and return its per-step results.

    An adapter failure (the interface never came up, the process died) is caught
    and recorded as ``result.error`` rather than raised, so one broken scenario
    never aborts a whole suite — the report still shows how far it got.
    """
    result = ScenarioResult(name=scenario.get("name", "unnamed"),
                            platform=scenario.get("platform", adapter.platform))
    try:
        adapter.open()
        for step in scenario.get("steps", []):
            action = step["action"]
            expect = step.get("expect")
            capture = adapter.send(action)
            ok = expect is None or expect in capture
            note = "" if ok else f"expected {expect!r} in output, not found"
            result.steps.append(StepResult(action, capture, expect, ok, note))
    except Exception as exc:  # noqa: BLE001 — any driver failure is a scenario error
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            adapter.close()
        except Exception:  # noqa: BLE001 — teardown must never mask the result
            pass
    return result


def run_suite(adapter_for: Any, scenarios: list[dict[str, Any]],
              platform: str) -> list[ScenarioResult]:
    """Run every scenario tagged for ``platform``; ``adapter_for`` builds a fresh
    adapter per scenario so state never leaks between them."""
    results = []
    for scn in scenarios:
        if scn.get("platform", "cli") != platform:
            continue
        results.append(run_scenario(adapter_for(), scn))
    return results
