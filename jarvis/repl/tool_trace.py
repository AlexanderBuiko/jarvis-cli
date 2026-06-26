"""
Surface the gateway's per-call tool trace in the REPL — cleanly.

The gateway logs one line per tool call to the ``jarvis.tools`` logger (order,
target server, tool, compact args, result preview). Rather than let those records
hit the root logger (timestamped, interleaving with the spinner), we buffer them
here and let the REPL print them as a tidy block *after* the turn finishes.

Usage:
    install()            # once, when MCP tools are enabled
    ...run a turn...
    for line in drain(): print(line)   # show what the agent did, then clear
"""

from __future__ import annotations

import logging

_LOGGER_NAME = "jarvis.tools"


class _TraceCollector(logging.Handler):
    """Buffers formatted ``jarvis.tools`` messages until the REPL drains them."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


_collector: _TraceCollector | None = None


def install() -> None:
    """Attach the collector to the ``jarvis.tools`` logger (idempotent).

    Sets propagate=False so these lines don't also reach the root logger — the
    REPL owns their presentation.
    """
    global _collector
    if _collector is not None:
        return
    _collector = _TraceCollector()
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.addHandler(_collector)
    logger.propagate = False


def drain() -> list[str]:
    """Return the tool-trace lines collected since the last drain, and clear them."""
    if _collector is None:
        return []
    lines, _collector.lines = _collector.lines, []
    return lines
