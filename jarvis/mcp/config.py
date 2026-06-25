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

import os
import sys
from dataclasses import dataclass, field

# Supported transports. ``stdio`` launches the server as a subprocess (the
# original local model). The two network transports connect to an already-running
# server by URL — that's what makes the server's lifecycle independent of the CLI
# (start it separately; if it's down it simply contributes no tools).
STDIO = "stdio"
STREAMABLE_HTTP = "streamable-http"
SSE = "sse"
_NETWORK_TRANSPORTS = {STREAMABLE_HTTP, SSE}


@dataclass(frozen=True)
class MCPServerConfig:
    """How to reach one MCP server.

    name:      short identifier, also the namespace prefix for its tools.
    transport: ``stdio`` (subprocess) | ``streamable-http`` | ``sse`` (network).

    stdio only:
        command: executable to launch (defaults to the current Python).
        args:    arguments passed to the command.
        env:     extra environment variables for the subprocess.

    network only:
        url:         the server's endpoint (e.g. http://localhost:8080/mcp).
        api_key_env: name of an env var holding the API key; when set and
                     present, its value is sent as the ``X-API-Key`` header.
    """

    name: str
    transport: str = STDIO
    # stdio
    command: str = sys.executable
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # network
    url: str | None = None
    api_key_env: str | None = None

    def __post_init__(self) -> None:
        if self.transport in _NETWORK_TRANSPORTS and not self.url:
            raise ValueError(f"{self.name}: transport {self.transport!r} requires a url")
        if self.transport not in (_NETWORK_TRANSPORTS | {STDIO}):
            raise ValueError(f"{self.name}: unknown transport {self.transport!r}")


# The remote server's namespace prefix. Every tool it exposes is surfaced to the
# rest of Jarvis as ``jarvis.<tool>`` (e.g. ``jarvis.get_weather_digest``), which
# is why the standalone server hosts time *and* weather tools under one name.
REMOTE_SERVER_NAME = "jarvis"

# Env vars carrying the remote server's URL. JARVIS_MCP_URL is the current name;
# JARVIS_TIME_MCP_URL is still honoured so existing ~/.jarvis/.env files keep
# working (it pre-dates the server growing beyond time).
REMOTE_URL_ENV = "JARVIS_MCP_URL"
REMOTE_URL_ENV_LEGACY = "JARVIS_TIME_MCP_URL"

# There is no local fleet any more: the standalone network server is the single
# source of MCP tools. Kept (empty) for the public API and tests that build on it.
DEFAULT_SERVERS: list[MCPServerConfig] = []


def default_servers() -> list[MCPServerConfig]:
    """Build the active fleet, reading the environment *at call time*.

    Env is read here — not at import — so it reflects values loaded from .env
    files at startup (see jarvis.config.env_file). The standalone Jarvis MCP
    server is wired in *explicitly* by setting JARVIS_MCP_URL (or the legacy
    JARVIS_TIME_MCP_URL); unset → no MCP tools. If the configured server is down
    the registry records the failure rather than crashing (see MCPRegistry).
    """
    servers = list(DEFAULT_SERVERS)
    url = (os.environ.get(REMOTE_URL_ENV, "").strip()
           or os.environ.get(REMOTE_URL_ENV_LEGACY, "").strip())
    if url:
        servers.append(
            MCPServerConfig(
                name=REMOTE_SERVER_NAME,
                transport=STREAMABLE_HTTP,
                url=url,
                api_key_env="MCP_API_KEY",  # unset locally → no header sent (server open)
            )
        )
    return servers
