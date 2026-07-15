"""Local stdio MCP servers bundled with the CLI.

These run as subprocesses launched by the CLI's MCP client (see ``jarvis/mcp/``).
They exist for tools that must read *local* machine state — a remote server cannot
see the developer's working tree — the canonical example being the current git
branch.
"""
