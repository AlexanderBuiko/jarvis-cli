"""
A minimal stdio MCP server used **only by the test suite**.

The product no longer ships a local stdio server (the standalone network server
is the single source of tools), but the stdio transport path — SDK handshake,
tool discovery, namespaced routing and graceful teardown — still needs end-to-end
coverage. This tiny fixture provides it without depending on the network server.

Launched as a subprocess by the live registry tests via ``-m tests.stdio_server``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

# WARNING log level keeps per-request INFO noise off the inherited stderr.
mcp = FastMCP("fixture", log_level="WARNING")


@mcp.tool()
def echo(text: str) -> str:
    """Return the input unchanged — a connectivity smoke-test tool."""
    return text


@mcp.tool()
def ping() -> str:
    """Return a constant — a trivial no-argument tool."""
    return "pong"


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
