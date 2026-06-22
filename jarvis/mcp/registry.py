"""
MCPRegistry — connect to many MCP servers and present one aggregated tool space.

This is the extensibility layer (Phase 5). The single-server :class:`MCPClient`
knows nothing about its peers; the registry owns the *fleet*:

  • **Connection** — opens every configured server, tolerating partial failure:
    one dead server doesn't sink the others (its error is recorded and skipped).
  • **Aggregation** — merges each server's tools into one catalogue.
  • **Namespacing & collisions** — every tool is exposed as ``<server>.<tool>``
    (e.g. ``weather.get_weather``). Because the prefix is the server name, which
    is unique by construction, two servers can both expose a ``search`` tool with
    no clash. The bare name is kept too, as a convenience alias *only when it is
    unambiguous* across the fleet.
  • **Routing** — ``call_tool("weather.get_weather", …)`` strips the prefix and
    dispatches to the owning client.

It is an async context manager: ``async with MCPRegistry(configs) as reg: …``
connects everything on enter and tears it all down on exit.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from .client import MCPClient, MCPConnectionError
from .config import MCPServerConfig

NAMESPACE_SEP = "."


@dataclass(frozen=True)
class AggregatedTool:
    """One tool in the merged catalogue, tagged with its owning server."""

    server: str
    name: str            # bare name as the server advertises it
    description: str
    input_schema: dict

    @property
    def qualified_name(self) -> str:
        return f"{self.server}{NAMESPACE_SEP}{self.name}"


class MCPRegistry:
    """A connected fleet of MCP servers behind one aggregated interface."""

    def __init__(self, configs: list[MCPServerConfig]) -> None:
        self._configs = configs
        self._clients: dict[str, MCPClient] = {}
        self._stack: AsyncExitStack | None = None
        # Populated by connect(): server name → connection error string.
        self.failures: dict[str, str] = {}

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def connect(self) -> "MCPRegistry":
        """Connect every configured server. Partial failure is tolerated."""
        self._stack = AsyncExitStack()
        self.failures = {}
        for config in self._configs:
            client = MCPClient(config)
            try:
                await client.connect()
            except MCPConnectionError as exc:
                self.failures[config.name] = str(exc)
                continue
            # connect() already opened the connection in *this* task; register its
            # teardown as a callback so it closes in the same task. (Entering the
            # client as a context manager here would re-run connect() and leak the
            # first connection's cancel scope — the source of anyio's
            # "exit cancel scope in a different task" error.)
            self._stack.push_async_callback(client.aclose)
            self._clients[config.name] = client
        return self

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._clients = {}

    async def __aenter__(self) -> "MCPRegistry":
        return await self.connect()

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ── Introspection ───────────────────────────────────────────────────────

    @property
    def connected_servers(self) -> list[str]:
        return list(self._clients)

    async def list_tools(self) -> list[AggregatedTool]:
        """Return every tool across every connected server, namespaced."""
        catalogue: list[AggregatedTool] = []
        for name, client in self._clients.items():
            for tool in await client.list_tools():
                catalogue.append(AggregatedTool(
                    server=name,
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=getattr(tool, "inputSchema", {}) or {},
                ))
        return catalogue

    # ── Routing ─────────────────────────────────────────────────────────────

    def _resolve(self, name: str, catalogue: list[AggregatedTool]) -> AggregatedTool:
        """Map a qualified or (unambiguous) bare tool name to its AggregatedTool."""
        if NAMESPACE_SEP in name:
            server, bare = name.split(NAMESPACE_SEP, 1)
            for tool in catalogue:
                if tool.server == server and tool.name == bare:
                    return tool
            raise KeyError(f"No tool {name!r} on connected servers.")
        # Bare name: accept only if exactly one server provides it.
        matches = [t for t in catalogue if t.name == name]
        if not matches:
            raise KeyError(f"No tool named {name!r} on connected servers.")
        if len(matches) > 1:
            owners = ", ".join(t.qualified_name for t in matches)
            raise KeyError(f"Ambiguous tool {name!r}; qualify it: {owners}")
        return matches[0]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None):
        """Invoke a tool by qualified (``server.tool``) or unambiguous bare name."""
        tool = self._resolve(name, await self.list_tools())
        return await self._clients[tool.server].call_tool(tool.name, arguments)
