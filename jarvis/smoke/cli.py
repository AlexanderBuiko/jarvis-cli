"""
CLIAdapter — drives the real Jarvis REPL through a pseudo-terminal.

The terminal is jarvis's only user-facing surface, so this is the honest
Level-2 target: launch the actual ``python -m jarvis`` process and type into it,
exactly as a user would. prompt-toolkit needs a real tty, so a plain stdin pipe
will not do — the stdlib ``pty`` module gives us one without adding a dependency
(``pexpect`` would be the obvious tool but is not worth a new runtime dep for a
harness this small).

Determinism: the driver sends command-mode input only (``config``, ``task``,
``thread`` …), which never calls the LLM, so a run needs no network and repeats
exactly. Chat-mode prompts are out of scope here — they belong to the live tier.
Readiness is detected by a quiet period (no new bytes for a short window) rather
than by parsing the redrawn prompt, which is full of cursor-movement escapes.
"""

from __future__ import annotations

import os
import pty
import re
import select
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path

from ..session.profile_store import ProfileStore

# Strip ALL ANSI/VT sequences, not just colour — prompt-toolkit emits cursor
# moves, screen clears and bracketed-paste markers that would make a capture
# unreadable. (session/store.py only needs the colour subset; we need the lot.)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[=>]|\r")

# Hard ceiling on waiting for one command's output (also covers the slow first
# read while the process boots and negotiates the terminal).
_STEP_TIMEOUT_S = 12.0


class CLIAdapter:
    """Spawns the REPL in a pty and drives it one command at a time.

    Satisfies ``SmokeAdapter`` structurally. Command mode is entered once on
    ``open`` (the REPL toggles prompt/command mode with a bare ``!``), so each
    ``send`` is a plain command line.
    """

    platform = "cli"

    def __init__(self, env: dict[str, str] | None = None) -> None:
        # Each adapter gets its own throwaway HOME so a run never reads or writes
        # the real ~/.jarvis, and so state cannot leak between scenarios.
        self._home = tempfile.mkdtemp(prefix="jarvis-smoke-")
        # A dummy key so startup never blocks on credentials; command mode never
        # calls the engine, so the value is never used.
        self._env = {
            **os.environ, "HOME": self._home,
            "OPENROUTER_API_KEY": "smoke-dummy", "JARVIS_MCP_URL": "",
            **(env or {}),
        }
        self._pid: int | None = None
        self._fd: int | None = None
        self._seq = 0

    def open(self) -> None:
        # Seed a default profile so the first-run onboarding interview does not
        # fire and consume the scenario's commands — the run must be deterministic.
        ProfileStore(directory=Path(self._home) / ".jarvis" / "memory").write_default()
        pid, fd = pty.fork()
        if pid == 0:  # child: become the REPL
            os.execve(sys.executable, [sys.executable, "-m", "jarvis"], self._env)
        self._pid, self._fd = pid, fd
        os.write(fd, b"!\n")          # prompt mode → command mode
        self._read_to_sentinel("")    # absorb boot + banner up to a known-ready point

    def send(self, action: str) -> str:
        """Type one command line and return the cleaned output it produced.

        A unique sentinel command is sent right after, and output is read until the
        REPL's "Unknown command" reply to it appears. That delimits this command's
        output deterministically — no reliance on timing, which the terminal's
        cursor-position negotiation makes unreliable during boot.
        """
        if self._fd is None:
            raise RuntimeError("adapter is not open")
        os.write(self._fd, action.encode() + b"\n")
        return self._clean(self._read_to_sentinel(action), action)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.write(self._fd, b"exit\n")
            except OSError:
                pass
        if self._pid is not None:
            try:
                os.kill(self._pid, signal.SIGKILL)
                os.waitpid(self._pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        self._pid = self._fd = None
        shutil.rmtree(self._home, ignore_errors=True)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _read_to_sentinel(self, action: str) -> str:
        """Send a unique unknown command and read until its reply; return the text
        before it — everything the real ``action`` produced."""
        self._seq += 1
        token = f"__smoke_sync_{self._seq}__"
        marker = f"Unknown command: '{token}'"
        os.write(self._fd, token.encode() + b"\n")
        raw = ""
        deadline = time.time() + _STEP_TIMEOUT_S
        while time.time() < deadline:
            r, _, _ = select.select([self._fd], [], [], 0.2)
            if not r:
                continue
            try:
                data = os.read(self._fd, 4096)
            except OSError:
                break
            if not data:
                break
            raw += data.decode("utf-8", "replace")
            if marker in _ANSI.sub("", raw):
                break
        cleaned = _ANSI.sub("", raw)
        cut = cleaned.find(marker)
        return cleaned[:cut] if cut != -1 else cleaned

    @staticmethod
    def _clean(text: str, action: str) -> str:
        """Keep the meaningful result lines: drop echoes, the status bar, the
        sync sentinel and the terminal's CPR warning."""
        keep = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s == action or s == "!" + action or s.startswith("!"):
                continue                          # echoed input
            if "__smoke_sync_" in s:
                continue                          # the sentinel and its echo
            if "tokens" in s and "·" in s:
                continue                          # the redrawn status bar
            if s.startswith("WARNING: your terminal"):
                continue                          # prompt-toolkit CPR notice
            keep.append(ln.rstrip())
        return "\n".join(keep).strip()
