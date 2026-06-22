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

from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import MCPServerConfig


class MCPConnectionError(RuntimeError):
    """Raised when a server can't be launched or the handshake fails."""


class MCPClient:
    """A live connection to a single MCP server."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise MCPConnectionError(f"{self.name}: not connected (call connect() first)")
        return self._session

    async def connect(self) -> "MCPClient":
        """Launch the server subprocess and complete the MCP handshake."""
        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env or None,
        )
        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception as exc:  # noqa: BLE001 — normalise every startup failure
            await stack.aclose()
            raise MCPConnectionError(f"{self.name}: connection failed: {exc}") from exc
        self._stack = stack
        self._session = session
        return self

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

    async def __aenter__(self) -> "MCPClient":
        return await self.connect()

    async def __aexit__(self, *exc) -> None:
        await self.aclose()
