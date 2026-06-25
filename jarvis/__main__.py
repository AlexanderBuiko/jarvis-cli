"""
Entry point: python -m jarvis
Also exposed as the 'jarvis' console script via setup.cfg.
"""

import sys
from .config.manager import ConfigManager
from .openrouter.client import OpenRouterClient
from .agent import JarvisAgent
from .repl.loop import run_repl


def _start_mcp():
    """Connect the local MCP fleet so its tools are available each turn.

    Best-effort: if the SDK isn't installed or the fleet won't start, Jarvis runs
    normally without tools. Returns the provider (or None) and a status line.
    """
    try:
        from .mcp.provider import MCPToolProvider
    except ImportError:
        return None, "MCP: not installed (chat/tasks run without tools)"
    try:
        provider = MCPToolProvider().start()
    except Exception as exc:  # noqa: BLE001 — never block startup on MCP
        return None, f"MCP: unavailable ({exc})"
    tools = provider.tool_specs()
    status = f"MCP: {len(tools)} tool(s) from {', '.join(provider.connected_servers) or 'no servers'}"
    if provider.failures:
        status += f"  ·  failed: {', '.join(provider.failures)}"
    return provider, status


def main() -> None:
    # Load ~/.jarvis/.env and ./.env before anything reads the environment, so
    # OPENROUTER_API_KEY / JARVIS_MCP_URL etc. come from config files and
    # need not be re-exported each run. Real env vars still take precedence.
    from .config.env_file import load_env_files
    applied = load_env_files()
    if applied:
        print(f"Config: loaded {', '.join(applied)}")

    try:
        config_manager = ConfigManager()
        client = OpenRouterClient()
    except EnvironmentError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(1)

    tool_provider, mcp_status = _start_mcp()
    print(mcp_status)

    agent = JarvisAgent(client, config_manager, tool_provider=tool_provider)
    try:
        run_repl(agent, config_manager)
    finally:
        if tool_provider is not None:
            tool_provider.close()


if __name__ == "__main__":
    main()
