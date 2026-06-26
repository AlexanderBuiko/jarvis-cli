"""
MCPClient — an async wrapper around one MCP server connection.

The official SDK exposes a connection as two nested async context managers:
``stdio_client(params)`` yields a (read, write) stream pair, and
``ClientSession(read, write)`` turns those into an initialised session. Keeping a
long-lived connection open therefore means holding both contexts open for the
client's lifetime — we use an ``AsyncExitStack`` for exactly that, so a single
``aclose()`` tears everything down in the right order.

This class deliberately owns *one* server. Aggregation across servers, namespacing
and routing live one layer up in :class:`jarvis.mcp.registry.MCPRegistry`, so the
client stays small and the multi-server policy is isolated and testable.
"""

from __future__ import annotations

import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import SSE, STREAMABLE_HTTP, MCPServerConfig

# Header used to carry the API key to a network MCP server. The server-side
# auth middleware (added at the deployment step) checks the same header.
API_KEY_HEADER = "X-API-Key"

_NETWORK_TRANSPORTS = {STREAMABLE_HTTP, SSE}
# How long to wait for the liveness/auth probe before giving up on a server.
PREFLIGHT_TIMEOUT_S = 4


class MCPConnectionError(RuntimeError):
    """Raised when a server can't be launched or the handshake fails."""


class MCPClient:
    """A live connection to a single MCP server."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
        self._errlog = None  # stdio subprocess stderr sink (opened on connect)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise MCPConnectionError(f"{self.name}: not connected (call connect() first)")
        return self._session

    def _auth_headers(self) -> dict[str, str] | None:
        """Build request headers for a network server, injecting the API key.

        Returns None when no key is configured/present, so a local server running
        without auth is reached with no header. The key value is read from the env
        var named by ``api_key_env`` and is never logged.
        """
        if not self.config.api_key_env:
            return None
        key = os.environ.get(self.config.api_key_env, "").strip()
        return {API_KEY_HEADER: key} if key else None

    async def _open_streams(self, stack: AsyncExitStack):
        """Open the transport and return its (read, write) stream pair.

        This is the *only* place that knows about transport. stdio launches a
        subprocess; the network transports connect to a running server by URL.
        Everything above (ClientSession, the registry, the bridge) is identical
        across transports.
        """
        transport = self.config.transport
        if transport == STREAMABLE_HTTP:
            from mcp.client.streamable_http import streamablehttp_client

            # streamable-http yields a 3-tuple (read, write, get_session_id).
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(self.config.url, headers=self._auth_headers())
            )
            return read, write
        if transport == SSE:
            from mcp.client.sse import sse_client

            read, write = await stack.enter_async_context(
                sse_client(self.config.url, headers=self._auth_headers())
            )
            return read, write
        # Default: stdio subprocess. A stdio MCP server logs to *its* stderr, which
        # the SDK forwards to ``errlog`` (default sys.stderr) — that's the startup
        # banner / per-request noise that otherwise floods the REPL. Send it to a
        # log file (JARVIS_MCP_LOG) or, by default, discard it; MCP traffic itself
        # rides stdout and is unaffected.
        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env or None,
        )
        self._errlog = self._open_errlog()
        read, write = await stack.enter_async_context(stdio_client(params, errlog=self._errlog))
        return read, write

    @staticmethod
    def _open_errlog():
        """Where a stdio server's stderr goes: a JARVIS_MCP_LOG file, else devnull."""
        path = os.environ.get("JARVIS_MCP_LOG", "").strip()
        return open(path, "a", encoding="utf-8") if path else open(os.devnull, "w")

    async def _preflight(self) -> None:
        """Fail fast — before opening a real MCP connection — if a network server
        is unreachable *or* rejects our API key.

        Why this exists: tearing down a *half-open* streamable-http/SSE connection
        (server down, or it 401s mid-handshake) triggers an unavoidable anyio
        "cancel scope in a different task" error from inside the transport's own
        task group. It surfaces from the async-generator finalizer, so it can't be
        caught at our layer and it corrupts teardown of the *whole* fleet. The cure
        is to never create that half-open connection: a cheap probe decides both
        liveness and auth first, so a down/unauthorized server raises a clean
        MCPConnectionError here and the streamable client is never entered.

        The probe is a tiny POST the auth middleware evaluates: a missing/invalid
        key yields 401/403 (auth failure); a valid key against the MCP endpoint
        yields some other status (e.g. 400 "missing session id") — reachable, so we
        proceed. The probe creates no MCP session, so there's nothing to leak.
        """
        import httpx

        headers = dict(self._auth_headers() or {})
        headers.setdefault("Accept", "application/json, text/event-stream")
        headers.setdefault("Content-Type", "application/json")
        probe_body = b'{"jsonrpc":"2.0","id":0,"method":"ping"}'
        try:
            async with httpx.AsyncClient(timeout=PREFLIGHT_TIMEOUT_S) as http:
                resp = await http.post(self.config.url, content=probe_body, headers=headers)
        except Exception as exc:  # noqa: BLE001 — connection refused / DNS / timeout
            raise MCPConnectionError(f"server unreachable at {self.config.url} ({exc})") from exc
        if resp.status_code in (401, 403):
            raise MCPConnectionError(
                f"unauthorized (HTTP {resp.status_code}) — set/check MCP_API_KEY"
            )

    async def connect(self) -> "MCPClient":
        """Connect to the server (launch or dial) and complete the MCP handshake."""
        if self.config.transport in _NETWORK_TRANSPORTS:
            await self._preflight()  # raises MCPConnectionError if the server is down
        stack = AsyncExitStack()
        try:
            read, write = await self._open_streams(stack)
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception as exc:  # noqa: BLE001 — normalise every startup failure
            await self._safe_aclose(stack)
            raise MCPConnectionError(f"{self.name}: connection failed: {exc}") from exc
        self._stack = stack
        self._session = session
        return self

    @staticmethod
    async def _safe_aclose(stack: AsyncExitStack) -> None:
        """Tear down a partially-opened connection, swallowing teardown noise.

        Unwinding a *half-open* network transport (e.g. the server refused the
        connection mid-handshake) can make anyio raise "Attempted to exit cancel
        scope in a different task" from inside the transport's own task group.
        The connection is already dead, so that teardown error is not actionable —
        suppress it and let the caller surface a clean MCPConnectionError instead,
        which is what the registry's partial-failure handling expects.
        """
        try:
            await stack.aclose()
        except Exception:  # noqa: BLE001 — teardown-of-a-dead-connection noise only
            pass

    async def list_tools(self) -> list[Any]:
        """Return the server's advertised tools (name, description, input schema)."""
        result = await self.session.list_tools()
        return list(result.tools)

    async def call_tool(self, tool: str, arguments: dict[str, Any] | None = None):
        """Invoke a tool by its bare (un-namespaced) name."""
        return await self.session.call_tool(tool, arguments or {})

    async def aclose(self) -> None:
        """Close the session and stop the server subprocess."""
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None
        if self._errlog is not None:
            try:
                self._errlog.close()
            except Exception:  # noqa: BLE001 — closing the log sink must never raise
                pass
            self._errlog = None

    async def __aenter__(self) -> "MCPClient":
        return await self.connect()

    async def __aexit__(self, *exc) -> None:
        await self.aclose()
