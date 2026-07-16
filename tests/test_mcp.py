"""
Tests for the MCP integration (jarvis.mcp).

The live tests drive a small **stdio fixture server** (tests/stdio_server.py) over
the same path the CLI uses — exercising the full SDK handshake, tool discovery,
namespaced routing and graceful teardown end to end. No network is required: the
fixture's echo/ping tools are fully local. (The product ships no local stdio
server; the standalone network server is the single source of real tools.)

The bridge and collision logic are tested without a connection.
"""

import asyncio
import unittest
import unittest.mock

from jarvis.mcp import MCPRegistry
from jarvis.mcp.bridge import tools_to_openrouter
from jarvis.mcp.client import MCPConnectionError
from jarvis.mcp.config import MCPServerConfig
from jarvis.mcp.registry import AggregatedTool, MCPRegistry as Registry

# The stdio fixture server, launched as a subprocess for the live tests.
FIXTURE_SERVERS = [MCPServerConfig(name="fixture", args=["-m", "tests.stdio_server"])]


def _run(coro):
    return asyncio.run(coro)


class MCPRegistryLiveTest(unittest.TestCase):
    """End-to-end against the stdio fixture server."""

    def test_connect_and_list_tools(self):
        async def scenario():
            async with MCPRegistry(FIXTURE_SERVERS) as reg:
                self.assertEqual(reg.connected_servers, ["fixture"])
                self.assertEqual(reg.failures, {})
                names = {t.qualified_name for t in await reg.list_tools()}
                return names
        names = _run(scenario())
        self.assertIn("fixture.echo", names)
        self.assertIn("fixture.ping", names)

    def test_call_echo_roundtrip(self):
        async def scenario():
            async with MCPRegistry(FIXTURE_SERVERS) as reg:
                result = await reg.call_tool("fixture.echo", {"text": "ping"})
                return result.content[0].text
        self.assertEqual(_run(scenario()), "ping")

    def test_call_bare_name_returns_text(self):
        async def scenario():
            async with MCPRegistry(FIXTURE_SERVERS) as reg:
                result = await reg.call_tool("ping", {})  # unambiguous bare name
                return result.content[0].text
        self.assertEqual(_run(scenario()), "pong")

    def test_unknown_tool_raises(self):
        async def scenario():
            async with MCPRegistry(FIXTURE_SERVERS) as reg:
                await reg.call_tool("fixture.nope", {})
        with self.assertRaises(KeyError):
            _run(scenario())


class NetworkTransportDegradationTest(unittest.TestCase):
    """A down network server must degrade gracefully, not crash the fleet."""

    def test_down_http_server_is_skipped_stdio_survives(self):
        from jarvis.mcp.config import STREAMABLE_HTTP

        # Port 9 (discard) refuses MCP — a stand-in for "server not running".
        configs = [
            MCPServerConfig(name="fixture", args=["-m", "tests.stdio_server"]),
            MCPServerConfig(name="jarvis", transport=STREAMABLE_HTTP,
                            url="http://127.0.0.1:9/mcp"),
        ]

        async def scenario():
            async with MCPRegistry(configs) as reg:
                names = {t.qualified_name for t in await reg.list_tools()}
                return reg.connected_servers, dict(reg.failures), names

        connected, failures, names = _run(scenario())
        # The stdio fixture stays up; the unreachable HTTP server is recorded, not fatal.
        self.assertEqual(connected, ["fixture"])
        self.assertIn("jarvis", failures)
        self.assertIn("fixture.echo", names)
        self.assertNotIn("jarvis.get_current_time", names)


class NetworkPreflightTest(unittest.TestCase):
    """The auth-aware preflight classifies down / unauthorized / reachable."""

    def _client(self, *, api_key_env=None):
        from jarvis.mcp.client import MCPClient
        from jarvis.mcp.config import STREAMABLE_HTTP, MCPServerConfig
        return MCPClient(MCPServerConfig(
            name="time", transport=STREAMABLE_HTTP,
            url="http://server.invalid/mcp", api_key_env=api_key_env,
        ))

    def _patch_httpx(self, status=None, raises=None):
        import httpx

        class _Resp:
            def __init__(self, code): self.status_code = code

        class _FakeClient:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, content=None, headers=None):
                if raises is not None:
                    raise raises
                return _Resp(status)

        return unittest.mock.patch.object(httpx, "AsyncClient", _FakeClient)

    def test_401_is_unauthorized(self):
        with self._patch_httpx(status=401):
            with self.assertRaises(MCPConnectionError) as ctx:
                _run(self._client()._preflight())
        self.assertIn("unauthorized", str(ctx.exception).lower())

    def test_connection_error_is_unreachable(self):
        import httpx
        with self._patch_httpx(raises=httpx.ConnectError("refused")):
            with self.assertRaises(MCPConnectionError) as ctx:
                _run(self._client()._preflight())
        self.assertIn("unreachable", str(ctx.exception).lower())

    def test_400_means_reachable_and_authed(self):
        # 400 "missing session id" = server accepted the key; preflight must pass.
        with self._patch_httpx(status=400):
            _run(self._client()._preflight())  # no raise


class NetworkConfigValidationTest(unittest.TestCase):
    """Network transports must declare a url."""

    def test_http_without_url_is_rejected(self):
        from jarvis.mcp.config import STREAMABLE_HTTP, MCPServerConfig
        with self.assertRaises(ValueError):
            MCPServerConfig(name="time", transport=STREAMABLE_HTTP)

    def test_unknown_transport_is_rejected(self):
        from jarvis.mcp.config import MCPServerConfig
        with self.assertRaises(ValueError):
            MCPServerConfig(name="x", transport="carrier-pigeon", url="http://x")


class CollisionAndBridgeTest(unittest.TestCase):
    """Namespacing / collision policy and the function-calling bridge (no I/O)."""

    def _catalogue(self):
        return [
            AggregatedTool("weather", "search", "find city", {"type": "object"}),
            AggregatedTool("github", "search", "find repo", {"type": "object"}),
            AggregatedTool("weather", "get_weather", "current weather", {"type": "object"}),
        ]

    def test_bare_name_is_ambiguous_across_servers(self):
        reg = Registry([])
        with self.assertRaises(KeyError) as ctx:
            reg._resolve("search", self._catalogue())
        self.assertIn("Ambiguous", str(ctx.exception))

    def test_qualified_name_resolves_each_server(self):
        reg = Registry([])
        cat = self._catalogue()
        self.assertEqual(reg._resolve("weather.search", cat).server, "weather")
        self.assertEqual(reg._resolve("github.search", cat).server, "github")

    def test_unambiguous_bare_name_resolves(self):
        reg = Registry([])
        self.assertEqual(reg._resolve("get_weather", self._catalogue()).server, "weather")

    def test_bridge_emits_api_legal_wire_names(self):
        import re
        specs = tools_to_openrouter(self._catalogue())
        names = {s["function"]["name"] for s in specs}
        # Wire names replace the dot separator so they match the API name pattern.
        self.assertEqual(names, {"weather__search", "github__search", "weather__get_weather"})
        for name in names:
            self.assertRegex(name, r"^[a-zA-Z0-9_-]{1,64}$")
        self.assertEqual(specs[0]["type"], "function")


class _ToolLoopEngine:
    """Fake engine: emits a tool call on the first turn, a final answer after."""

    def __init__(self, answer="Final answer."):
        self.answer = answer
        self.calls: list[tuple[list[dict], dict]] = []

    def complete(self, messages, params):
        from jarvis.openrouter.client import Completion
        self.calls.append((messages, params))
        # Has a tool result already been fed back? Then produce the final answer.
        if any(m.get("role") == "tool" for m in messages):
            tool_calls = None
            text = self.answer
        else:
            tool_calls = [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "weather__get_weather",  # wire name, as a model emits
                             "arguments": '{"city": "London"}'},
            }]
            text = ""
        return Completion(
            text=text, finish_reason="stop",
            request={"messages": messages}, response={"usage": {"total_tokens": 2}},
            latency_ms=0.0, tool_calls=tool_calls,
        )

    def get_pricing(self, _):
        return (None, None)

    def get_context_window(self, _):
        return None


class _FakeProvider:
    def __init__(self):
        self.called: list[tuple[str, dict]] = []

    def tool_specs(self):
        return [{"type": "function", "function": {"name": "weather__get_weather",
                 "description": "", "parameters": {"type": "object"}}}]

    def call_tool(self, name, args):
        self.called.append((name, args))
        return "London: 12°C, rain"


class GatewayToolLoopTest(unittest.TestCase):
    """The gateway executes tool calls and feeds results back until a final answer."""

    def _gateway(self, engine, provider):
        from jarvis.llm.gateway import LLMGateway
        return LLMGateway(engine, tool_provider=provider)

    def test_tool_call_is_executed_and_fed_back(self):
        engine, provider = _ToolLoopEngine("It's raining in London."), _FakeProvider()
        gw = self._gateway(engine, provider)
        calls: list[dict] = []
        completion = gw.complete(
            [{"role": "user", "content": "weather in London?"}], {},
            label="final_answer", api_calls=calls, use_tools=True,
        )
        self.assertEqual(completion.text, "It's raining in London.")
        self.assertEqual(provider.called, [("weather__get_weather", {"city": "London"})])
        self.assertEqual(len(engine.calls), 2)       # tool round + final answer
        self.assertEqual(len(calls), 2)              # both rounds billed

    def test_use_tools_false_never_offers_tools(self):
        engine, provider = _ToolLoopEngine(), _FakeProvider()
        gw = self._gateway(engine, provider)
        gw.complete([{"role": "user", "content": "hi"}], {}, use_tools=False)
        # tools must not appear in the params the engine saw
        self.assertNotIn("tools", engine.calls[0][1])
        self.assertEqual(provider.called, [])

    def test_no_provider_is_plain_completion(self):
        from jarvis.llm.gateway import LLMGateway
        engine = _ToolLoopEngine()
        gw = LLMGateway(engine)  # no provider
        gw.complete([{"role": "user", "content": "hi"}], {}, use_tools=True)
        self.assertNotIn("tools", engine.calls[0][1])

    def test_tool_exchange_is_appended_to_caller_messages(self):
        # The invariant checker depends on seeing the tool exchange, so the loop
        # must append it to the caller's own list (not a private copy).
        engine, provider = _ToolLoopEngine(), _FakeProvider()
        gw = self._gateway(engine, provider)
        messages = [{"role": "user", "content": "weather?"}]
        gw.complete(messages, {}, use_tools=True)
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["user", "assistant", "tool"])
        self.assertTrue(messages[1].get("tool_calls"))

    def test_first_call_payload_is_a_frozen_snapshot(self):
        # Regression: the first call's recorded request must not show later rounds'
        # tool messages (the reference-aliasing bug).
        engine, provider = _ToolLoopEngine(), _FakeProvider()
        gw = self._gateway(engine, provider)
        gw.complete([{"role": "user", "content": "weather?"}], {}, use_tools=True)
        first_call_messages = engine.calls[0][0]
        self.assertEqual([m["role"] for m in first_call_messages], ["user"])


class _WriteLoopEngine:
    """Fake engine: emits a files.write_file call first, then a final answer."""

    def complete(self, messages, params):
        from jarvis.openrouter.client import Completion
        if any(m.get("role") == "tool" for m in messages):
            tool_calls, text = None, "Done."
        else:
            tool_calls = [{
                "id": "w1", "type": "function",
                "function": {"name": "files__write_file",
                             "arguments": '{"path": "x.md", "content": "hi"}'},
            }]
            text = ""
        return Completion(text=text, finish_reason="stop", request={}, response={},
                          latency_ms=0.0, tool_calls=tool_calls)

    def get_pricing(self, _):
        return (None, None)

    def get_context_window(self, _):
        return None


class _WriteProvider:
    def __init__(self):
        self.called: list[tuple[str, dict]] = []

    def tool_specs(self):
        return [{"type": "function", "function": {"name": "files__write_file",
                 "description": "", "parameters": {"type": "object"}}}]

    def call_tool(self, name, args):
        self.called.append((name, args))
        return "[created 'x.md']"


class GatewayPermissionGateTest(unittest.TestCase):
    """A mutating tool call is dispatched only when the gate allows it."""

    def _run(self, gate):
        from jarvis.llm.gateway import LLMGateway
        provider = _WriteProvider()
        gw = LLMGateway(_WriteLoopEngine(), tool_provider=provider, tool_gate=gate)
        messages = [{"role": "user", "content": "write x.md"}]
        gw.complete(messages, {}, use_tools=True)
        return provider, messages

    def test_unauthorised_write_is_queued_not_dispatched(self):
        from jarvis.mcp.permissions import ToolPermissions
        gate = ToolPermissions()                          # ask-mode: queue for approval
        provider, messages = self._run(gate)
        self.assertEqual(provider.called, [])             # never reached the provider
        self.assertEqual(len(gate.pending), 1)            # queued instead
        tool_msg = next(m for m in messages if m["role"] == "tool")
        self.assertIn("awaiting", tool_msg["content"].lower())

    def test_authorised_write_is_dispatched(self):
        from jarvis.mcp.permissions import ToolPermissions
        gate = ToolPermissions(auto=True)
        provider, _ = self._run(gate)
        self.assertEqual(provider.called,
                         [("files__write_file", {"path": "x.md", "content": "hi"})])
        self.assertEqual(gate.pending, [])

    def test_no_gate_dispatches_as_before(self):
        provider, _ = self._run(None)
        self.assertEqual(len(provider.called), 1)


class _DryRunEngine:
    """Fake engine: emits a dry-run write_file call, then a final answer."""

    def complete(self, messages, params):
        from jarvis.openrouter.client import Completion
        if any(m.get("role") == "tool" for m in messages):
            tool_calls, text = None, "Preview shown."
        else:
            tool_calls = [{
                "id": "d1", "type": "function",
                "function": {"name": "files__write_file",
                             "arguments": '{"path": "x.md", "content": "hi", "dry_run": true}'},
            }]
            text = ""
        return Completion(text=text, finish_reason="stop", request={}, response={},
                          latency_ms=0.0, tool_calls=tool_calls)

    def get_pricing(self, _):
        return (None, None)

    def get_context_window(self, _):
        return None


class _DryRunProvider:
    def tool_specs(self):
        return [{"type": "function", "function": {"name": "files__write_file",
                 "description": "", "parameters": {"type": "object"}}}]

    def call_tool(self, name, args):
        return "[dry run — would create]\n--- a/x.md\n+++ b/x.md\n@@ -0,0 +1 @@\n+hi"


class GatewayDryRunPreviewTest(unittest.TestCase):
    """A dry-run write is captured for a read-only frame, not dumped to the model."""

    def test_dry_run_is_captured_and_summarised(self):
        from jarvis.llm.gateway import LLMGateway
        from jarvis.mcp.permissions import ToolPermissions
        gate = ToolPermissions()
        gw = LLMGateway(_DryRunEngine(), tool_provider=_DryRunProvider(), tool_gate=gate)
        messages = [{"role": "user", "content": "preview x.md"}]
        gw.complete(messages, {}, use_tools=True)
        # captured on the gate for the REPL to frame
        self.assertEqual(len(gate.previews), 1)
        self.assertEqual(gate.previews[0]["path"], "x.md")
        # the model got a short summary, NOT the raw diff body
        tool_msg = next(m for m in messages if m["role"] == "tool")
        self.assertIn("shown to the user", tool_msg["content"])
        self.assertNotIn("+hi", tool_msg["content"])


class _PipelineEngine:
    """Fake engine that drives the weather-anomaly chain A→B→C.

    On each turn it looks at how many tool results have come back and emits the
    next tool call, relaying the *previous* tool's output forward as the argument —
    exactly how a real model chains get_weather_readings → detect_weather_anomalies
    → send_telegram_alert. After the third result it returns a final answer.
    """

    _CHAIN = [
        ("jarvis__get_weather_readings", "city"),       # round 1: no prior output
        ("jarvis__detect_weather_anomalies", "weather_report"),
        ("jarvis__send_telegram_alert", "anomaly_report"),
    ]

    def __init__(self):
        self.calls = []

    def complete(self, messages, params):
        from jarvis.openrouter.client import Completion
        self.calls.append((messages, params))
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        step = len(tool_msgs)
        if step >= len(self._CHAIN):
            return Completion(text="Alert sent for Tokyo.", finish_reason="stop",
                              request={}, response={}, latency_ms=0.0, tool_calls=None)
        name, arg_key = self._CHAIN[step]
        # Relay the previous tool's output as this call's argument (data transfer).
        prior = tool_msgs[-1]["content"] if tool_msgs else "Tokyo"
        import json as _json
        args = _json.dumps({arg_key: prior})
        return Completion(
            text="", finish_reason="stop", request={}, response={}, latency_ms=0.0,
            tool_calls=[{"id": f"call_{step}", "type": "function",
                         "function": {"name": name, "arguments": args}}],
        )

    def get_pricing(self, _):
        return (None, None)

    def get_context_window(self, _):
        return None


class _PipelineProvider:
    """Canned pipeline tool outputs; records the call order and relayed args."""

    def __init__(self):
        self.called = []

    def tool_specs(self):
        return [{"type": "function", "function": {"name": n, "description": "",
                 "parameters": {"type": "object"}}}
                for n in ("jarvis__get_weather_readings",
                          "jarvis__detect_weather_anomalies",
                          "jarvis__send_telegram_alert")]

    def call_tool(self, name, args):
        self.called.append((name, args))
        if name == "jarvis__get_weather_readings":
            return '{"report_type": "weather_readings.v1", "city": "Tokyo", "daily": []}'
        if name == "jarvis__detect_weather_anomalies":
            return '{"city": "Tokyo", "anomaly_count": 1, "anomalies": [{"type": "rapid_temperature_drop"}]}'
        if name == "jarvis__send_telegram_alert":
            return '{"sent": true, "anomaly_count": 1}'
        raise KeyError(name)


class PipelineChainingTest(unittest.TestCase):
    """jarvis-cli chains the three pipeline tools and relays data between them."""

    def test_three_tool_chain_executes_in_order(self):
        from jarvis.llm.gateway import LLMGateway
        engine, provider = _PipelineEngine(), _PipelineProvider()
        gw = LLMGateway(engine, tool_provider=provider)
        calls = []
        completion = gw.complete(
            [{"role": "user", "content": "Analyze Tokyo weather for the last week; "
                                         "alert me if it's unusual."}],
            {}, label="answer", api_calls=calls, use_tools=True,
        )
        order = [name for name, _ in provider.called]
        self.assertEqual(order, ["jarvis__get_weather_readings",
                                 "jarvis__detect_weather_anomalies",
                                 "jarvis__send_telegram_alert"])
        # Data transfer: detect received the readings report; alert received the
        # anomaly report (each call's arg is the previous tool's output).
        self.assertIn("weather_readings.v1", provider.called[1][1]["weather_report"])
        self.assertIn("anomaly_count", provider.called[2][1]["anomaly_report"])
        self.assertEqual(completion.text, "Alert sent for Tokyo.")
        self.assertEqual(len(calls), 4)  # 3 tool rounds + final answer, all billed


class MultiServerConfigTest(unittest.TestCase):
    """servers.json declares a multi-server fleet (network + stdio) as data."""

    def _write(self, tmpdir, body):
        import os
        path = os.path.join(tmpdir, "servers.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def test_loads_three_servers_with_env_expansion(self):
        import json
        import os
        import tempfile
        from jarvis.mcp.config import STDIO, STREAMABLE_HTTP, default_servers

        body = json.dumps({"servers": [
            {"name": "jarvis", "transport": "streamable-http",
             "url": "https://jarvis.example/mcp", "api_key_env": "MCP_API_KEY"},
            {"name": "translation", "transport": "stdio", "command": "npx",
             "args": ["-y", "@libretranslate/mcp"],
             "env": {"LIBRETRANSLATE_API_URL": "${LIBRETRANSLATE_API_URL}"}},
            {"name": "worldnews", "transport": "stdio", "command": "npx",
             "args": ["-y", "world-news-api-mcp"],
             "env": {"WORLD_NEWS_API_KEY": "${WORLD_NEWS_API_KEY}"}},
        ]})
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, body)
            with unittest.mock.patch.dict(os.environ,
                                          {"JARVIS_SERVERS_FILE": path,
                                           "LIBRETRANSLATE_API_URL": "https://lt.example",
                                           "WORLD_NEWS_API_KEY": "secret-key"}):
                servers = default_servers()

        by_name = {s.name: s for s in servers}
        self.assertEqual(set(by_name), {"jarvis", "translation", "worldnews"})
        self.assertEqual(by_name["jarvis"].transport, STREAMABLE_HTTP)   # network +
        self.assertEqual(by_name["translation"].transport, STDIO)        # stdio mix loads
        self.assertEqual(by_name["worldnews"].transport, STDIO)
        # ${VAR} resolved from the real environment, not stored literally…
        self.assertEqual(by_name["translation"].env["LIBRETRANSLATE_API_URL"], "https://lt.example")
        self.assertEqual(by_name["worldnews"].env["WORLD_NEWS_API_KEY"], "secret-key")
        # …and the parent env (PATH) is merged in so npx is still found.
        self.assertIn("PATH", by_name["worldnews"].env)

    def test_falls_back_to_single_url_when_no_file(self):
        import os
        from jarvis.mcp.config import default_servers

        env = {k: v for k, v in os.environ.items()
               if k not in ("JARVIS_SERVERS_FILE", "JARVIS_MCP_URL", "JARVIS_TIME_MCP_URL")}
        env["JARVIS_MCP_URL"] = "https://only.example/mcp"
        # cwd has no servers.json in the test working dir tree we control here;
        # force the file lookup to miss by pointing the env var at a nonexistent path.
        env["JARVIS_SERVERS_FILE"] = "/nonexistent/servers.json"
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            servers = default_servers()
        self.assertEqual([s.name for s in servers], ["jarvis"])
        self.assertEqual(servers[0].url, "https://only.example/mcp")


class _MultiServerEngine:
    """Fake engine driving the 8-step, 3-server Tokyo scenario, one call per round."""

    CHAIN = [
        ("jarvis__get_weather_readings", "city"),
        ("jarvis__detect_weather_anomalies", "weather_report"),
        ("worldnews__get_geo_coordinates", "location"),
        ("worldnews__search_news", "location"),
        ("worldnews__retrieve_news_articles", "ids"),
        ("translation__translate", "text"),
        ("jarvis__get_current_time", "city"),
        ("jarvis__send_telegram_alert", "anomaly_report"),
    ]

    def __init__(self):
        self.calls = []

    def complete(self, messages, params):
        from jarvis.openrouter.client import Completion
        self.calls.append((messages, params))
        step = sum(1 for m in messages if m.get("role") == "tool")
        if step >= len(self.CHAIN):
            return Completion(text="Summary sent.", finish_reason="stop",
                              request={}, response={}, latency_ms=0.0, tool_calls=None)
        name, key = self.CHAIN[step]
        prior = [m for m in messages if m.get("role") == "tool"]
        import json as _json
        arg = prior[-1]["content"] if prior else "Tokyo"
        return Completion(
            text="", finish_reason="stop", request={}, response={}, latency_ms=0.0,
            tool_calls=[{"id": f"c{step}", "type": "function",
                         "function": {"name": name, "arguments": _json.dumps({key: arg})}}])

    def get_pricing(self, _):
        return (None, None)

    def get_context_window(self, _):
        return None


class _MultiServerProvider:
    """Records (server, tool) per call and resolves server like the real provider."""

    RESULTS = {
        "jarvis__get_weather_readings": '{"report_type":"weather_readings.v1","city":"Tokyo"}',
        "jarvis__detect_weather_anomalies": '{"city":"Tokyo","anomaly_count":1,"anomalies":[{"type":"rapid_temperature_drop"}]}',
        "worldnews__get_geo_coordinates": '{"lat":35.68,"lon":139.69}',
        "worldnews__search_news": '{"ids":[1,2,3]}',
        "worldnews__retrieve_news_articles": '{"articles":[{"title":"嵐が東京に接近"}]}',
        "translation__translate": '{"translated_text":"Storm approaches Tokyo"}',
        "jarvis__get_current_time": "Tokyo: Tue, 2026-06-26 21:00 (Asia/Tokyo)",
        "jarvis__send_telegram_alert": '{"sent":true,"anomaly_count":1}',
    }

    def __init__(self):
        self.routed = []  # (server, tool) in call order

    def tool_specs(self):
        return [{"type": "function", "function": {"name": n, "description": "",
                 "parameters": {"type": "object"}}} for n in self.RESULTS]

    def server_for(self, name):
        return name.split("__", 1)[0] if "__" in name else "?"

    def call_tool(self, name, args):
        self.routed.append((self.server_for(name), name))
        return self.RESULTS[name]


class MultiServerFlowTest(unittest.TestCase):
    """Long cross-server flow: correct selection, routing, order, and trace."""

    def test_eight_step_three_server_flow(self):
        from jarvis.llm.gateway import LLMGateway
        engine, provider = _MultiServerEngine(), _MultiServerProvider()
        gw = LLMGateway(engine, tool_provider=provider)
        api_calls = []
        with self.assertLogs("jarvis.tools", level="INFO") as logs:
            completion = gw.complete(
                [{"role": "user", "content": "Analyze Tokyo weather; if unusual, "
                                             "gather news + city context and alert me."}],
                {}, label="answer", api_calls=api_calls, use_tools=True)

        # Correct selection + order across the three servers.
        self.assertEqual([t for _, t in provider.routed],
                         [name for name, _ in _MultiServerEngine.CHAIN])
        # Correct routing: each call went to the right server.
        servers_in_order = [s for s, _ in provider.routed]
        self.assertEqual(servers_in_order,
                         ["jarvis", "jarvis", "worldnews", "worldnews", "worldnews",
                          "translation", "jarvis", "jarvis"])
        self.assertEqual({*servers_in_order}, {"jarvis", "worldnews", "translation"})
        # Long flow completed within the (raised) round cap: 8 tools + final answer.
        self.assertEqual(len(provider.routed), 8)
        self.assertEqual(completion.text, "Summary sent.")
        self.assertEqual(len(api_calls), 9)
        # Trace shows order index + target server + bare tool name for each call.
        joined = "\n".join(logs.output)
        self.assertIn("[1] jarvis.get_weather_readings(", joined)
        self.assertIn("[6] translation.translate(", joined)
        self.assertIn("[8] jarvis.send_telegram_alert(", joined)

    def test_flow_exceeds_old_six_round_cap(self):
        # Regression guard: the 8-step flow would have been truncated at the old
        # MAX_TOOL_ROUNDS=6. Confirm the cap is high enough now.
        from jarvis.llm.gateway import MAX_TOOL_ROUNDS
        self.assertGreaterEqual(MAX_TOOL_ROUNDS, len(_MultiServerEngine.CHAIN))


class InvariantToolContextTest(unittest.TestCase):
    """Tool-sourced facts must not be flagged as fabrication."""

    def test_tool_context_extracted_from_messages(self):
        from jarvis.pipeline.invariants import _tool_context
        msgs = [
            {"role": "user", "content": "weather?"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"function": {"name": "weather__get_weather",
                                          "arguments": '{"city": "Moscow"}'}}]},
            {"role": "tool", "content": "Moscow: 18.8C, clear"},
        ]
        ctx = _tool_context(msgs)
        self.assertIn("weather__get_weather", ctx)
        self.assertIn("Moscow: 18.8C, clear", ctx)

    def test_no_tools_yields_empty_context(self):
        from jarvis.pipeline.invariants import _tool_context
        self.assertEqual(_tool_context([{"role": "user", "content": "hi"}]), "")

    def test_corrected_tag_gives_calm_notice(self):
        from jarvis.pipeline.invariants import _interpret_resolution
        text, notice = _interpret_resolution("CORRECTED:\nMoscow is 18.8°C (source: Open-Meteo).")
        self.assertEqual(text, "Moscow is 18.8°C (source: Open-Meteo).")
        self.assertIn("adjusted to stay within", notice)
        self.assertNotIn("conflict", notice.lower())

    def test_refused_tag_gives_conflict_notice(self):
        from jarvis.pipeline.invariants import _interpret_resolution
        text, notice = _interpret_resolution("REFUSED:\nI can't give medical advice.")
        self.assertEqual(text, "I can't give medical advice.")
        self.assertIn("conflicts", notice.lower())

    def test_untagged_resolution_falls_back(self):
        from jarvis.pipeline.invariants import _interpret_resolution
        text, notice = _interpret_resolution("some rewritten reply")
        self.assertEqual(text, "some rewritten reply")
        self.assertIsNotNone(notice)

    def test_check_prompt_marks_tool_output_trusted(self):
        from jarvis.prompt_builder.builder import build_invariant_check_prompt
        prompt = build_invariant_check_prompt("No fabrication.", "Moscow is 19C",
                                              "- called weather__get_weather\n  → returned: 18.8C")
        self.assertIn("TRUSTED", prompt)
        self.assertIn("NOT fabrication", prompt)
        # No tool context → no tool block.
        plain = build_invariant_check_prompt("No fabrication.", "Moscow is 19C")
        self.assertNotIn("TOOL ACTIVITY", plain)


if __name__ == "__main__":
    unittest.main()
