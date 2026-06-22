"""
Tests for the MCP integration (jarvis.mcp).

These drive the *real* local weather server over stdio — the same path the CLI
uses — so they exercise the full SDK handshake, tool discovery, namespaced
routing and graceful teardown end to end. No network is required: get_weather
falls back to deterministic mock data when offline, and echo is fully local.

The bridge and collision logic are tested without a connection.
"""

import asyncio
import unittest

from jarvis.mcp import DEFAULT_SERVERS, MCPRegistry
from jarvis.mcp.bridge import tools_to_openrouter
from jarvis.mcp.registry import AggregatedTool, MCPRegistry as Registry


def _run(coro):
    return asyncio.run(coro)


class MCPRegistryLiveTest(unittest.TestCase):
    """End-to-end against the local weather stdio server."""

    def test_connect_and_list_tools(self):
        async def scenario():
            async with MCPRegistry(DEFAULT_SERVERS) as reg:
                self.assertEqual(reg.connected_servers, ["weather"])
                self.assertEqual(reg.failures, {})
                names = {t.qualified_name for t in await reg.list_tools()}
                return names
        names = _run(scenario())
        self.assertIn("weather.get_weather", names)
        self.assertIn("weather.echo", names)

    def test_call_echo_roundtrip(self):
        async def scenario():
            async with MCPRegistry(DEFAULT_SERVERS) as reg:
                result = await reg.call_tool("weather.echo", {"text": "ping"})
                return result.content[0].text
        self.assertEqual(_run(scenario()), "ping")

    def test_call_weather_returns_text(self):
        async def scenario():
            async with MCPRegistry(DEFAULT_SERVERS) as reg:
                result = await reg.call_tool("get_weather", {"city": "London"})
                return result.content[0].text
        text = _run(scenario())
        self.assertIn("London", text)

    def test_unknown_tool_raises(self):
        async def scenario():
            async with MCPRegistry(DEFAULT_SERVERS) as reg:
                await reg.call_tool("weather.nope", {})
        with self.assertRaises(KeyError):
            _run(scenario())


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
