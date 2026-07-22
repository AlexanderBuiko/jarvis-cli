"""
WebAdapter — drives the real web UI in a headless browser via Playwright.

The automated counterpart of driving the page by hand with a browser MCP: it
starts ``python -m jarvis.web`` as a subprocess, opens the page in a headless
Chromium, types each command into the page's command box, clicks Run, and reads
the rendered result. Same ``SmokeAdapter`` contract as the CLI adapter, so the
runner and the scenario format are unchanged — a scenario is a command string
either way, and the platform only decides which interface executes it.

Playwright is an *optional* dependency (the ``web`` extra), imported lazily so a
default install and the CLI smoke never require it. When it is absent the adapter
raises a clear install hint, which the runner records as a scenario error rather
than a crash.

"Headless" = the browser engine runs with no visible window, the way a CI machine
(which has no display) runs UI tests. That is what makes this, unlike the MCP
run, automatable in a pipeline.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

# The output element starts each command as this sentinel, so the wait succeeds
# even when two commands in a row produce identical text.
_WAIT_SENTINEL = "__smoke_wait__"
_SERVER_BOOT_TIMEOUT_S = 20.0
_STEP_TIMEOUT_MS = 8000


def _free_port() -> int:
    """Ask the OS for an unused TCP port (bind to 0, read it back, release)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(url: str, timeout: float) -> None:
    """Poll ``url`` until it answers or ``timeout`` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    raise RuntimeError(f"web server did not come up at {url} within {timeout:.0f}s")


class WebAdapter:
    """Runs the web UI in headless Chromium and drives it via the command box.

    Satisfies ``SmokeAdapter`` structurally. Lifecycle: ``open`` starts the server
    and the browser; ``send`` runs one command through the page; ``close`` tears
    both down and must not raise on an already-dead target.
    """

    platform = "web"

    def __init__(self, port: int | None = None) -> None:
        self._port = port or _free_port()
        self._url = f"http://127.0.0.1:{self._port}/"
        self._proc: subprocess.Popen | None = None
        self._pw = None
        self._browser = None
        self._page = None

    def open(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed. Enable the web adapter with:\n"
                "  pip install -e .[web] && playwright install chromium"
            ) from exc

        self._proc = subprocess.Popen(
            [sys.executable, "-m", "jarvis.web", "--port", str(self._port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _wait_for_server(self._url, _SERVER_BOOT_TIMEOUT_S)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._page = self._browser.new_page()
        self._page.goto(self._url)

    def send(self, action: str) -> str:
        """Type ``action`` into the command box, run it, return the page result."""
        if self._page is None:
            raise RuntimeError("adapter is not open")
        page = self._page
        # Reset the result to a sentinel so the wait detects the new output even
        # when it equals the previous command's output.
        page.evaluate(
            "(s) => { document.querySelector('#output').textContent = s; }", _WAIT_SENTINEL
        )
        page.fill("#cmd", action)
        page.click("#run")
        page.wait_for_function(
            "(s) => document.querySelector('#output').textContent !== s",
            arg=_WAIT_SENTINEL, timeout=_STEP_TIMEOUT_MS,
        )
        return page.inner_text("#output")

    def close(self) -> None:
        for teardown in (
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
        ):
            try:
                teardown()
            except Exception:  # noqa: BLE001 — teardown must never mask the result
                pass
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = self._pw = self._browser = self._page = None
