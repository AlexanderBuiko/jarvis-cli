"""
Live end-to-end demonstration of the multi-server MCP flow.

Registers the declared fleet (jarvis [remote] + wikipedia + worldnews [stdio]),
then asks the agent a single question that requires tools from all three servers.
The agent itself selects the tools, the registry routes each call to its owning
server, and the per-call trace (jarvis.tools logger) prints the order, target
server, and result — satisfying the "selected tool / target server / call order /
result" tracing requirement.

Prerequisites
-------------
  * OPENROUTER_API_KEY                (in ~/.jarvis/.env or the environment)
  * a servers.json fleet file         (see servers.json.example)
  * JARVIS_MCP_URL (+ MCP_API_KEY)    the deployed jarvis server with the
                                      weather-anomaly pipeline tools
  * WORLD_NEWS_API_KEY                worldnewsapi.com key (for the news steps)
  * wikipedia-mcp installed           pip install --user wikipedia-mcp
  * npx available                     for world-news-api-mcp

Run:
    python scripts/multiserver_scenario.py
"""
from __future__ import annotations

import logging
import sys

from jarvis.config.env_file import load_env_files
from jarvis.llm.gateway import LLMGateway
from jarvis.openrouter.client import DEFAULT_MODEL, OpenRouterClient
from jarvis.mcp.provider import MCPToolProvider

SCENARIO = (
    "Analyze the weather in Tokyo for the last week. If unusual conditions are "
    "detected, gather recent weather-related news near Tokyo, collect contextual "
    "information about the city, determine the current local time, and send me a "
    "Telegram summary that includes the anomalies, the local time, a short news "
    "digest, and the city context."
)

SYSTEM = (
    "You are Jarvis. You have tools from several MCP servers: 'jarvis' (weather "
    "readings, anomaly detection, current time, Telegram alerts), 'worldnews' "
    "(geo coordinates, news search and retrieval), and 'wikipedia' (article "
    "summaries). Use the tools to fully satisfy the request; pass each tool's "
    "output to the next as needed. Only send the Telegram alert once you have the "
    "anomalies, news, city context, and local time."
)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("jarvis.tools").setLevel(logging.INFO)

    applied = load_env_files()
    if applied:
        print(f"Config: loaded {', '.join(applied)}")

    try:
        engine = OpenRouterClient()
    except EnvironmentError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    provider = MCPToolProvider().start()
    print(f"\nConnected servers: {', '.join(provider.connected_servers) or '(none)'}")
    if provider.failures:
        for name, err in provider.failures.items():
            print(f"  ✗ {name}: {err}")
    print(f"Tools available: {len(provider.tool_specs())}\n")
    print("─" * 72)
    print("TOOL CALL TRACE (order · server · tool · result preview)")
    print("─" * 72)

    try:
        gateway = LLMGateway(engine, tool_provider=provider)
        api_calls: list[dict] = []
        completion = gateway.complete(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": SCENARIO}],
            {"model": DEFAULT_MODEL},
            label="multiserver_scenario", api_calls=api_calls, use_tools=True,
        )
    finally:
        provider.close()

    print("─" * 72)
    print(f"\nModel calls (billed): {len(api_calls)}")
    print(f"\nFinal answer:\n{completion.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
