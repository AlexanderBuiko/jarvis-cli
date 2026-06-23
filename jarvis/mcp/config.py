"""
MCP server configuration.

A server is described declaratively — a name plus how to launch it (command,
args, env). The registry consumes a list of these; adding a second or third
server later is a data change here, not a code change in the client. This mirrors
the rest of the codebase's "build from abstractions, wire concretes at the edge"
stance: the transport details live in config, the client depends only on the
shape.

For now every server is a local **stdio** subprocess (no cloud, no ports). The
same dataclass extends naturally to HTTP/SSE transports later by adding a
``transport`` field; the registry would branch on it when opening the connection.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MCPServerConfig:
    """How to reach one MCP server.

    name:    short identifier, also the namespace prefix for its tools.
    command: executable to launch (defaults to the current Python).
    args:    arguments passed to the command.
    env:     extra environment variables for the subprocess.
    """

    name: str
    command: str = sys.executable
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


# The default local fleet. Today it is a single weather server launched as a
# module subprocess; appending another MCPServerConfig here is all it takes to
# bring a second server online (see registry.MCPRegistry).
DEFAULT_SERVERS: list[MCPServerConfig] = [
    MCPServerConfig(
        name="weather",
        args=["-m", "jarvis.mcp.servers.weather"],
    ),
]
