"""
A minimal web front-end over the same Jarvis logic the REPL drives.

Purpose: give Level-2 smoke a *real* clickable UI. jarvis's only interface was
the terminal; this adds a web one so a browser driver (Playwright / Browser MCP)
can open a page, fill a form, click, and check the result — the literal Level-2
loop. It duplicates a slice of the CLI (config + tasks), not the whole thing:
enough for the "create entity → check → delete" smoke pattern.

Design: reuse, don't rebuild. The backend holds one JarvisAgent + ConfigManager
(exactly as ``__main__`` wires them, minus MCP/network) and routes each posted
command through the same ``_dispatch`` the REPL uses, so the web UI and the CLI
run identical logic. Only non-interactive commands are exposed (config, task
new/list/delete); interactive pipeline gates are out of scope here.

Stdlib ``http.server`` on purpose — no web framework, no new dependency; this is
a UI entry point (like ``repl/`` or ``mcp/cli``), so printing/serving here is
correct. HOME is redirected to a throwaway dir so a run never touches ~/.jarvis.
"""

from __future__ import annotations

import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_STATIC = Path(__file__).resolve().parent / "static"

# Commands the web UI is allowed to run. Anything interactive (task start/run,
# chat) needs a terminal controller and is deliberately not reachable here.
_ALLOWED = {"config", "task", "thread", "invariants", "help"}


class _NoController:
    """Stand-in for the REPL's InputController. The web backend runs only
    non-interactive commands, so any attempt to use it is a clear error rather
    than a hang."""

    def __getattr__(self, name: str):
        raise RuntimeError(f"web backend cannot run interactive command (needed '{name}')")


def run_command(command: str, agent, config, controller) -> str:
    """Route one posted command through the real ``_dispatch``, guarded.

    Only the ``_ALLOWED`` command families are reachable; anything else (chat,
    interactive task steps) returns a readable error instead of hanging on the
    absent controller. A handler raising degrades to ``error: …`` so one bad
    request never takes the server down.
    """
    from ..repl.loop import _dispatch

    head = command.split()[0].lower() if command else ""
    if head not in _ALLOWED:
        return f"error: '{head or command}' is not available in the web UI"
    try:
        return _dispatch(command, agent, config, controller)
    except SystemExit:
        return "(exit is disabled in the web UI)"
    except Exception as exc:  # noqa: BLE001 — a handler error must not kill the server
        return f"error: {exc}"


def _build_agent():
    """Wire a JarvisAgent the way __main__ does, minus MCP and the network."""
    from ..agent import JarvisAgent
    from ..config.manager import ConfigManager
    from ..llm.router import EngineRouter

    config = ConfigManager()
    router = EngineRouter(config, tool_provider=None, tool_gate=None)
    agent = JarvisAgent(None, config, tool_provider=None, router=router)
    return agent, config


class _Handler(BaseHTTPRequestHandler):
    # Set on the server instance in ``serve``.
    agent = None
    config = None
    controller = _NoController()

    def log_message(self, *args) -> None:  # noqa: D401 — silence the default stderr spam
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send_file("index.html", "text/html; charset=utf-8")
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self) -> None:
        if self.path != "/api/command":
            self._send(404, "application/json", b'{"error":"not found"}')
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            command = str(payload.get("command", "")).strip()
        except (ValueError, TypeError):
            self._send(400, "application/json", b'{"error":"bad json"}')
            return
        output = self._run(command)
        body = json.dumps({"output": output}).encode("utf-8")
        self._send(200, "application/json", body)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self, command: str) -> str:
        return run_command(command, self.agent, self.config, self.controller)

    def _send_file(self, name: str, content_type: str) -> None:
        try:
            data = (_STATIC / name).read_bytes()
        except OSError:
            self._send(404, "text/plain", b"missing static asset")
            return
        self._send(200, content_type, data)

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = 8765, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Build the agent and return a running server bound to ``host:port``.

    HOME is pointed at a throwaway directory before any store is constructed, so
    the web session's tasks/config live in isolation and never touch ~/.jarvis.
    """
    os.environ["HOME"] = tempfile.mkdtemp(prefix="jarvis-web-")
    os.environ.setdefault("OPENROUTER_API_KEY", "web-dummy")
    agent, config = _build_agent()
    _Handler.agent = agent
    _Handler.config = config
    server = ThreadingHTTPServer((host, port), _Handler)
    return server
