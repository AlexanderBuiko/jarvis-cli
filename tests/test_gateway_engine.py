"""Tests for GatewayEngine — routing every LLM call through the external proxy.

No socket and no provider: ``requests.post`` is faked, so these check only the
routing contract — messages flattened to (system, user), the reply mapped back to a
Completion, and a guard block degraded to an empty result rather than an exception.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from jarvis.llm import router
from jarvis.llm.router import GatewayEngine, _flatten_messages, make_engine


def _fake_post(status, body):
    sent = {}

    def _post(url, json=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        return SimpleNamespace(status_code=status, json=lambda: body)

    return _post, sent


class FlattenTest(unittest.TestCase):
    def test_system_and_history_collapse_into_two_roles(self):
        system, user = _flatten_messages([
            {"role": "system", "content": "you are a bot"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "help"},
        ])
        self.assertEqual(system, "you are a bot")
        self.assertIn("hi", user)
        self.assertIn("[assistant] hello", user)  # non-user roles keep a label
        self.assertIn("help", user)


class GatewayEngineTest(unittest.TestCase):
    def test_reply_is_mapped_to_a_completion_and_tools_are_off(self):
        post, sent = _fake_post(200, {"text": "ok", "model": "qwen2.5:7b",
                                      "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                                      "input_action": "allow"})
        eng = GatewayEngine("http://x:8900", downstream_provider="ollama")
        with mock.patch.object(router, "requests", SimpleNamespace(post=post)):
            c = eng.complete([{"role": "user", "content": "hi"}], {})
        self.assertEqual(c.text, "ok")
        self.assertIsNone(c.tool_calls)                 # proxy has no tool loop
        self.assertEqual(sent["url"], "http://x:8900/v1/complete")
        self.assertEqual(sent["json"]["provider"], "ollama")
        self.assertEqual((c.response.get("usage") or {}).get("prompt_tokens"), 5)

    def test_input_guard_block_degrades_to_empty_not_an_exception(self):
        post, _ = _fake_post(400, {"error": "blocked by input guard", "reason": "openai_key"})
        eng = GatewayEngine("http://x:8900", downstream_provider="ollama")
        with mock.patch.object(router, "requests", SimpleNamespace(post=post)):
            c = eng.complete([{"role": "user", "content": "key sk-proj-abc"}], {})
        self.assertEqual(c.text, "")
        self.assertEqual(c.finish_reason, "content_filter")

    def test_output_guard_block_returns_empty_text(self):
        post, _ = _fake_post(200, {"blocked": True, "text": "", "reason": "unsafe output"})
        eng = GatewayEngine("http://x:8900", downstream_provider="ollama")
        with mock.patch.object(router, "requests", SimpleNamespace(post=post)):
            c = eng.complete([{"role": "user", "content": "hi"}], {})
        self.assertEqual(c.text, "")

    def test_transport_error_raises(self):
        post, _ = _fake_post(502, {"error": "provider call failed"})
        eng = GatewayEngine("http://x:8900", downstream_provider="ollama")
        with mock.patch.object(router, "requests", SimpleNamespace(post=post)):
            with self.assertRaises(RuntimeError) as ctx:
                eng.complete([{"role": "user", "content": "hi"}], {})
        self.assertIn("gateway error 502", str(ctx.exception))

    def test_model_is_only_sent_when_explicitly_configured(self):
        post, sent = _fake_post(200, {"text": "ok"})
        eng = GatewayEngine("http://x:8900", downstream_provider="ollama")
        with mock.patch.object(router, "requests", SimpleNamespace(post=post)):
            eng.complete([{"role": "user", "content": "hi"}], {"model": "google/gemini-2.5-flash"})
        self.assertNotIn("model", sent["json"])  # runtime cloud default must not leak to a local downstream


class MakeEngineWiringTest(unittest.TestCase):
    def test_gateway_url_wraps_the_engine(self):
        with mock.patch.dict("os.environ", {"JARVIS_LLM_GATEWAY_URL": "http://x:8900"}):
            self.assertIsInstance(make_engine("ollama"), GatewayEngine)

    def test_no_gateway_url_returns_the_concrete_provider(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("JARVIS_LLM_GATEWAY_URL", None)
            self.assertNotIsInstance(make_engine("ollama"), GatewayEngine)


if __name__ == "__main__":
    unittest.main()
