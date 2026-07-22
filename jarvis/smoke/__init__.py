"""
jarvis.smoke — Level-2 UI smoke tests, driven through the real interface.

The runner is platform-agnostic; adapters plug in beneath a Protocol:

  adapter.py   SmokeAdapter Protocol + StepResult / ScenarioResult carriers
  cli.py       CLIAdapter — pty-drives the real REPL (the only UI today)
  runner.py    load JSON scenarios, run them through an adapter
  report.py    render results as one text report (captures = "screenshots")
  __main__.py  `python -m jarvis.smoke` — the CI entrypoint

A web adapter (Playwright / Browser MCP) or a mobile adapter (Claude-in-Mobile)
plugs in with no change to the runner, the scenarios or the report — the harness
is not tied to one platform, only one platform has a UI to drive right now.
"""

from .adapter import ScenarioResult, SmokeAdapter, StepResult
from .cli import CLIAdapter
from .report import render_report
from .runner import load_scenarios, run_scenario, run_suite

__all__ = [
    "SmokeAdapter",
    "StepResult",
    "ScenarioResult",
    "CLIAdapter",
    "load_scenarios",
    "run_scenario",
    "run_suite",
    "render_report",
]
