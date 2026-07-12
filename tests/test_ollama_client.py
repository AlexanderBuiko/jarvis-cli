"""Tests for the local Ollama chat engine (jarvis.ollama.client)."""

import os
import unittest
from unittest import mock

import requests

from jarvis.ollama.client import DEFAULT_MODEL, OllamaClient


def _chat_response(content="hi", model="qwen2.5:7b", tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return mock.Mock(
        status_code=200,
        json=mock.Mock(return_value={
            "model": model,
            "choices": [{"message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        }),
    )


class CompleteTest(unittest.TestCase):
    def test_posts_openai_shape_and_parses(self):
        resp = _chat_response(content="hello there")
        with mock.patch("jarvis.ollama.client.requests.post", return_value=resp) as post:
            c = OllamaClient(model="qwen2.5:7b").complete(
                [{"role": "user", "content": "hi"}], {"temperature": 0.2}
            )
        url, kwargs = post.call_args[0][0], post.call_args[1]
        self.assertTrue(url.endswith("/v1/chat/completions"))
        self.assertEqual(kwargs["json"]["model"], "qwen2.5:7b")
        self.assertEqual(kwargs["json"]["temperature"], 0.2)
        self.assertEqual(c.text, "hello there")
        self.assertEqual(c.finish_reason, "stop")
        self.assertEqual(c.response["usage"]["prompt_tokens"], 5)

    def test_pricing_is_free(self):
        self.assertEqual(OllamaClient().get_pricing("qwen2.5:7b"), (0.0, 0.0))

    def test_cloud_model_id_falls_back_to_local_default(self):
        # A live toggle cloud→local carries a slash-bearing cloud id that Ollama
        # can't run; the engine must substitute its own local default.
        resp = _chat_response()
        with mock.patch("jarvis.ollama.client.requests.post", return_value=resp) as post:
            OllamaClient(model="qwen2.5:7b").complete(
                [{"role": "user", "content": "hi"}], {"model": "google/gemini-2.5-flash"}
            )
        self.assertEqual(post.call_args[1]["json"]["model"], "qwen2.5:7b")

    def test_local_tag_is_honoured(self):
        resp = _chat_response()
        with mock.patch("jarvis.ollama.client.requests.post", return_value=resp) as post:
            OllamaClient(model="qwen2.5:7b").complete(
                [{"role": "user", "content": "hi"}], {"model": "llama3.1:8b"}
            )
        self.assertEqual(post.call_args[1]["json"]["model"], "llama3.1:8b")

    def test_tool_calls_passed_through(self):
        calls = [{"id": "1", "function": {"name": "t", "arguments": "{}"}}]
        resp = _chat_response(content=None, tool_calls=calls)
        with mock.patch("jarvis.ollama.client.requests.post", return_value=resp):
            c = OllamaClient().complete([{"role": "user", "content": "x"}], {"tools": [{"x": 1}]})
        self.assertEqual(c.tool_calls, calls)
        self.assertEqual(c.text, "")  # null content normalised to ""

    def test_unreachable_daemon_gives_actionable_error(self):
        with mock.patch("jarvis.ollama.client.requests.post",
                        side_effect=requests.ConnectionError("refused")):
            with self.assertRaises(RuntimeError) as ctx:
                OllamaClient().complete([{"role": "user", "content": "x"}], {})
        self.assertIn("ollama serve", str(ctx.exception))

    def test_http_error_surfaces_detail(self):
        resp = mock.Mock(status_code=404, text="model not found",
                         json=mock.Mock(return_value={"error": {"message": "model not found"}}))
        with mock.patch("jarvis.ollama.client.requests.post", return_value=resp):
            with self.assertRaises(RuntimeError) as ctx:
                OllamaClient().complete([{"role": "user", "content": "x"}], {})
        self.assertIn("model not found", str(ctx.exception))


class AuthHeaderTest(unittest.TestCase):
    def test_api_key_sent_when_set(self):
        resp = _chat_response()
        with mock.patch.dict(os.environ, {"JARVIS_OLLAMA_API_KEY": "secret"}), \
             mock.patch("jarvis.ollama.client.requests.post", return_value=resp) as post:
            OllamaClient(model="qwen2.5:7b").complete(
                [{"role": "user", "content": "hi"}], {}
            )
        self.assertEqual(post.call_args[1]["headers"], {"X-API-Key": "secret"})

    def test_no_header_when_unset(self):
        resp = _chat_response()
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch("jarvis.ollama.client.requests.post", return_value=resp) as post:
            os.environ.pop("JARVIS_OLLAMA_API_KEY", None)
            OllamaClient(model="qwen2.5:7b").complete(
                [{"role": "user", "content": "hi"}], {}
            )
        self.assertEqual(post.call_args[1]["headers"], {})


class ContextWindowTest(unittest.TestCase):
    def test_reads_and_caches_context_length(self):
        show = mock.Mock(status_code=200, json=mock.Mock(return_value={
            "model_info": {"qwen2.context_length": 32768}
        }))
        with mock.patch("jarvis.ollama.client.requests.post", return_value=show) as post:
            client = OllamaClient(model="qwen2.5:7b")
            self.assertEqual(client.get_context_window("qwen2.5:7b"), 32768)
            self.assertEqual(client.get_context_window("qwen2.5:7b"), 32768)
        self.assertEqual(post.call_count, 1)  # cached second time

    def test_missing_info_returns_none(self):
        show = mock.Mock(status_code=200, json=mock.Mock(return_value={}))
        with mock.patch("jarvis.ollama.client.requests.post", return_value=show):
            self.assertIsNone(OllamaClient().get_context_window("qwen2.5:7b"))


class ConfigTest(unittest.TestCase):
    def test_env_selects_model_and_url(self):
        with mock.patch.dict(os.environ, {
            "JARVIS_OLLAMA_MODEL": "phi3", "JARVIS_OLLAMA_URL": "http://box:1234/"
        }):
            client = OllamaClient()
        self.assertEqual(client.default_model, "phi3")
        self.assertEqual(client.url, "http://box:1234")

    def test_default_model_constant(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_OLLAMA_MODEL", None)
            self.assertEqual(OllamaClient().default_model, DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
