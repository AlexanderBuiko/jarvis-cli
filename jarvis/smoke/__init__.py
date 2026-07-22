"""
jarvis.smoke — Level-2 UI smoke tests, driven through the real interface.

The runner is platform-agnostic; adapters plug in beneath a Protocol:

  adapter.py   SmokeAdapter Protocol + StepResult / ScenarioResult carriers
  cli.py       CLIAdapter — pty-drives the real REPL
  web.py       WebAdapter — headless Chromium (Playwright) over the web UI
  runner.py    load JSON scenarios, run them through an adapter
  report.py    render results as one text report (captures = "screenshots")
  __main__.py  `python -m jarvis.smoke` — the CI entrypoint

A scenario is a command string, so the same scenario runs on any adapter; the
platform only decides which interface executes it. A mobile adapter
(Claude-in-Mobile) plugs in the same way. Playwright is an optional ``web`` extra.
"""

from .adapter import ScenarioResult, SmokeAdapter, StepResult
from .cli import CLIAdapter
from .report import render_report
from .runner import load_scenarios, run_scenario, run_suite
from .web import WebAdapter

__all__ = [
    "SmokeAdapter",
    "StepResult",
    "ScenarioResult",
    "CLIAdapter",
    "WebAdapter",
    "load_scenarios",
    "run_scenario",
    "run_suite",
    "render_report",
]
