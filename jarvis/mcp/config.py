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

import json
import logging
import os
import sys
from dataclasses import dataclass, field

logger = logging.getLogger("jarvis.mcp.config")

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


# A declarative fleet file lets several servers (network *and* stdio) be wired as
# data, not code — the multi-server story. Searched in this order; first hit wins:
#   1. $JARVIS_SERVERS_FILE   2. ./servers.json   3. ~/.jarvis/servers.json
SERVERS_FILE_ENV = "JARVIS_SERVERS_FILE"


def _servers_file_path() -> str | None:
    """Resolve the fleet-config file path from env/cwd/home, or None if absent."""
    explicit = os.environ.get(SERVERS_FILE_ENV, "").strip()
    candidates = [explicit] if explicit else [
        os.path.join(os.getcwd(), "servers.json"),
        os.path.join(os.path.expanduser("~"), ".jarvis", "servers.json"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _expand(value):
    """Expand ${VAR}/$VAR from the environment in any string (recursing lists/dicts).

    Keeps secrets *out* of the file: a server's api key is referenced as
    ``"${WORLD_NEWS_API_KEY}"`` and resolved from the real environment at load time.
    """
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def _config_from_entry(entry: dict) -> MCPServerConfig:
    """Turn one ``servers.json`` entry into an MCPServerConfig (env-expanded)."""
    entry = _expand(entry)
    transport = entry.get("transport", STDIO)
    env = entry.get("env") or {}
    if env:
        # A custom env *replaces* the subprocess environment in the SDK, so merge
        # over the parent's (PATH etc.) — otherwise npx / console scripts vanish.
        env = {**os.environ, **env}
    return MCPServerConfig(
        name=entry["name"],
        transport=transport,
        command=entry.get("command", sys.executable),
        args=list(entry.get("args", [])),
        env=env,
        url=entry.get("url"),
        api_key_env=entry.get("api_key_env"),
    )


def _load_servers_file(path: str) -> list[MCPServerConfig]:
    """Parse a ``servers.json`` fleet file into MCPServerConfigs.

    A malformed entry is skipped (logged), so one bad line doesn't sink the fleet —
    mirroring the registry's partial-failure stance.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    configs: list[MCPServerConfig] = []
    for entry in data.get("servers", []):
        try:
            configs.append(_config_from_entry(entry))
        except (KeyError, ValueError) as exc:
            logger.warning("skipping invalid server entry %r: %s", entry, exc)
    return configs


def default_servers() -> list[MCPServerConfig]:
    """Build the active fleet, reading config *at call time*.

    Precedence:
      1. A ``servers.json`` fleet file (env/cwd/home) — the multi-server path:
         any number of network and stdio servers, wired declaratively.
      2. Otherwise the legacy single-server env wiring: JARVIS_MCP_URL (or the
         legacy JARVIS_TIME_MCP_URL) → one streamable-http server.
      3. Otherwise no servers (no MCP tools).

    Config is read here — not at import — so it reflects values loaded from .env
    files at startup. A server that's down/unreachable is recorded by the registry
    rather than crashing the fleet.
    """
    path = _servers_file_path()
    if path:
        configs = _load_servers_file(path)
        if configs:
            logger.info("loaded %d MCP server(s) from %s", len(configs), path)
            return configs

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
