"""
MCPToolProvider — a long-lived, synchronous facade over the async MCP fleet.

The rest of Jarvis is synchronous; the MCP SDK is async, and its stdio/session
contexts must be **entered and exited in the same task**. This class satisfies
both: it runs a single background thread whose event loop holds one long-lived
"service" coroutine. That coroutine opens the :class:`MCPRegistry` once
(``async with``) and then serves tool calls off an internal queue until shutdown —
so connect, every call, and teardown all happen inside one task. No reconnecting
per turn, and none of anyio's "cancel scope in a different task" trouble.

Sync callers use three methods:

    provider.tool_specs()            → function-calling schema for the LLM request
    provider.call_tool(name, args)   → run a tool, get its text result
    provider.close()                 → stop the fleet (also registered at exit)

Construction is cheap; call :meth:`start` (or use it as a context manager) to
actually connect. Startup is fault-tolerant — a server that won't launch is
recorded in ``failures`` and skipped, mirroring the registry's own policy.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import os
import threading
from typing import Any

from .cli import _render_result
from .config import default_servers, MCPServerConfig
from .client import MCPConnectionError
from .registry import AggregatedTool, MCPRegistry
from .bridge import to_wire_name, tools_to_openrouter

# Stop a tool that hangs (or a wedged server) from blocking a turn forever. Public
# third-party servers (news/search APIs, cold stdio subprocesses) can legitimately
# take longer than a snappy local tool, so default generously and allow an override.
DEFAULT_CALL_TIMEOUT_S = float(os.environ.get("JARVIS_MCP_CALL_TIMEOUT_S", "60"))
# Bound how long we wait for the fleet to connect at startup.
DEFAULT_READY_TIMEOUT_S = 30


class MCPToolProvider:
    """A connected MCP fleet, usable from synchronous code."""

    def __init__(
        self,
        configs: list[MCPServerConfig] | None = None,
        *,
        ready_timeout: float = DEFAULT_READY_TIMEOUT_S,
        call_timeout: float = DEFAULT_CALL_TIMEOUT_S,
    ) -> None:
        self._configs = configs if configs is not None else default_servers()
        self._ready_timeout = ready_timeout
        self._call_timeout = call_timeout

        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: Exception | None = None

        self._tool_specs: list[dict] = []
        self._aggregated: list[AggregatedTool] = []
        # Wire name (API-legal, e.g. weather__get_weather) → dotted qualified name
        # the registry understands. Lets the model's tool_call route correctly.
        self._wire_to_qualified: dict[str, str] = {}
        self.failures: dict[str, str] = {}

        self._started = False
        self._closed = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> "MCPToolProvider":
        """Launch the background loop and connect the fleet. Idempotent."""
        if self._started:
            return self
        self._thread = threading.Thread(target=self._run, name="mcp-provider", daemon=True)
        self._thread.start()
        if not self._ready.wait(self._ready_timeout):
            raise MCPConnectionError("MCP provider did not become ready in time")
        if self._startup_error is not None:
            raise MCPConnectionError(f"MCP provider failed to start: {self._startup_error}")
        self._started = True
        atexit.register(self.close)
        return self

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception as exc:  # surface to start() via the ready gate
            self._startup_error = exc
            self._ready.set()

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        # The whole connection lifetime lives inside this one task.
        async with MCPRegistry(self._configs) as reg:
            self.failures = dict(reg.failures)
            self._aggregated = await reg.list_tools()
            self._tool_specs = tools_to_openrouter(self._aggregated)
            self._wire_to_qualified = {
                to_wire_name(t.qualified_name): t.qualified_name for t in self._aggregated
            }
            self._ready.set()
            while True:
                req = await self._queue.get()
                if req is None:  # shutdown sentinel
                    break
                name, args, fut = req
                try:
                    result = await reg.call_tool(name, args)
                    fut.set_result(_render_result(result))
                except Exception as exc:  # noqa: BLE001 — deliver to the caller
                    fut.set_exception(exc)

    def close(self) -> None:
        """Stop the fleet and join the background thread. Idempotent."""
        if not self._started or self._closed:
            return
        self._closed = True
        if self._loop is not None and self._queue is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        if self._thread is not None:
            self._thread.join(timeout=10)

    def __enter__(self) -> "MCPToolProvider":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    # ── Sync API used by the gateway / REPL ──────────────────────────────────

    @property
    def connected_servers(self) -> list[str]:
        return sorted({t.server for t in self._aggregated})

    def tools(self) -> list[AggregatedTool]:
        """The aggregated catalogue (for display)."""
        return list(self._aggregated)

    def tool_specs(self) -> list[dict]:
        """Function-calling tool schema to attach to an LLM request."""
        return list(self._tool_specs)

    def server_for(self, name: str) -> str:
        """Owning-server name for a tool (wire or dotted), for routing traces.

        Accepts the model's wire name (``wikipedia__get_summary``) or a dotted
        qualified name; returns the namespace prefix (the server). ``"?"`` if the
        name is unknown/un-namespaced.
        """
        qualified = self._wire_to_qualified.get(name, name)
        if "." in qualified:
            return qualified.split(".", 1)[0]
        # Bare name (the model can call an unambiguous tool without the prefix):
        # find its owning server in the aggregated catalogue.
        for tool in self._aggregated:
            if tool.name == name:
                return tool.server
        return "?"

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Run a tool on the background loop and return its text result (blocking)."""
        if not self._started or self._closed or self._loop is None or self._queue is None:
            raise MCPConnectionError("MCP provider is not running")
        # Accept the model's wire name (weather__get_weather) or a dotted name
        # (weather.get_weather, as the REPL passes). Unknown names fall through to
        # the registry, which raises a clear KeyError.
        qualified = self._wire_to_qualified.get(name, name)
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (qualified, arguments or {}, fut))
        return fut.result(timeout=self._call_timeout)
