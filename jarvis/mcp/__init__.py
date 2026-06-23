"""
jarvis.mcp — Model Context Protocol integration for Jarvis.

A small, extensible MCP layer built on the official MCP Python SDK:

  config.py    — declarative server descriptions (the local fleet)
  client.py    — MCPClient: one async connection to one server
  registry.py  — MCPRegistry: connect many servers, aggregate + route their tools
  bridge.py    — convert MCP tools to the LLM function-calling schema
  servers/     — local MCP servers we own (weather)
  cli.py       — `python -m jarvis.mcp` proof-of-concept front-end

The public surface is intentionally tiny: build a registry from configs, connect,
list tools, call tools.
"""

from .client import MCPClient, MCPConnectionError
from .config import DEFAULT_SERVERS, MCPServerConfig
from .registry import AggregatedTool, MCPRegistry

__all__ = [
    "MCPClient",
    "MCPConnectionError",
    "MCPServerConfig",
    "DEFAULT_SERVERS",
    "MCPRegistry",
    "AggregatedTool",
]
