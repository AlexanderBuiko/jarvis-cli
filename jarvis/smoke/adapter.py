"""
The smoke-test seam — one Protocol every platform driver satisfies.

Level-2 smoke drives the *real* interface end to end and records what it saw.
jarvis has one interface today (the terminal), but the tutor's brief is explicit
about not tying the harness to a single platform. So the runner talks to a
``SmokeAdapter`` Protocol, never to a concrete driver; the CLI adapter plugs in
beneath it, and a web adapter (Playwright/Browser MCP over a future web UI) or a
mobile adapter (Claude-in-Mobile) can plug in later with no change to the runner,
the scenarios, or the report.

A step's captured output is the CLI equivalent of a screenshot: the exact text
the interface produced, kept verbatim so a human can see what the agent saw.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class StepResult:
    """What one scenario step produced when driven through the interface."""

    action: str            # the input sent (a REPL command, a click, …)
    capture: str           # verbatim interface output — the "screenshot"
    expect: str | None     # substring the capture had to contain, or None
    passed: bool           # did the expectation hold (True when expect is None)
    note: str = ""         # why it failed, or a diagnostic hint


@dataclass
class ScenarioResult:
    """The outcome of running one scenario against one adapter."""

    name: str
    platform: str
    steps: list[StepResult] = field(default_factory=list)
    error: str | None = None   # set when the adapter itself broke (not a step)

    @property
    def passed(self) -> bool:
        """True only when the adapter held up and every step met its expectation."""
        return self.error is None and all(s.passed for s in self.steps)


@runtime_checkable
class SmokeAdapter(Protocol):
    """Drives one platform's real interface for the duration of a scenario.

    Lifecycle is ``open() → send(...) × N → close()``. ``send`` performs one
    action and returns exactly the interface output it produced, so the runner
    stays platform-agnostic: it never knows whether it drove a terminal, a page
    or a phone.
    """

    platform: str

    def open(self) -> None:
        """Start the interface (spawn the process, open the page …)."""
        ...

    def send(self, action: str) -> str:
        """Perform one action and return the verbatim output it produced."""
        ...

    def close(self) -> None:
        """Tear the interface down. Must not raise on an already-dead target."""
        ...
