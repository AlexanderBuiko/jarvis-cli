"""
Entry point: python -m jarvis
Also exposed as the 'jarvis' console script via setup.cfg.
"""

from .config.manager import ConfigManager
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

    config_manager = ConfigManager()

    tool_provider, mcp_status = _start_mcp()
    print(mcp_status)
    if tool_provider is not None:
        # Route the gateway's per-call tool trace to a tidy post-turn block.
        from .repl.tool_trace import install as install_tool_trace
        install_tool_trace()

    # The router builds engines lazily, per provider, so running fully local needs
    # no OPENROUTER_API_KEY (and vice-versa). A missing key surfaces only if/when a
    # turn actually routes to the cloud engine.
    from .llm.router import EngineRouter
    router = EngineRouter(config_manager, tool_provider=tool_provider)
    agent = JarvisAgent(None, config_manager, tool_provider=tool_provider, router=router)
    try:
        run_repl(agent, config_manager)
    finally:
        if tool_provider is not None:
            tool_provider.close()


if __name__ == "__main__":
    main()
