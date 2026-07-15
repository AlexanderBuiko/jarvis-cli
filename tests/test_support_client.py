"""Tests for the CLI `support` client (jarvis/repl/commands.py)."""

import requests

import jarvis.repl.commands as cmds


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeAgent:
    tool_provider = None


def test_support_endpoint_from_mcp_url(monkeypatch):
    monkeypatch.delenv("JARVIS_SUPPORT_URL", raising=False)
    monkeypatch.setenv("JARVIS_MCP_URL", "http://host:8080/mcp")
    endpoint, error = cmds._support_endpoint()
    assert error is None
    assert endpoint == "http://host:8080/support"


def test_support_query_sends_ticket_and_renders(monkeypatch):
    monkeypatch.setenv("JARVIS_SUPPORT_URL", "http://localhost:8080")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp(200, {
            "answer": "Set the key.",
            "ticket": {"id": "T-1002", "subject": "Authorization not working"},
            "notice": "grounded in 4 FAQ excerpt(s); ticket T-1002",
        })

    monkeypatch.setattr(requests, "post", fake_post)
    out = cmds.handle_support_query(
        ["Why", "isn't", "auth", "working?", "ticket=T-1002"], _FakeAgent()
    )
    assert captured["url"] == "http://localhost:8080/support"
    assert captured["json"]["ticket_id"] == "T-1002"
    assert captured["json"]["question"] == "Why isn't auth working?"
    assert "Set the key." in out
    assert "ticket T-1002" in out


def test_support_query_needs_a_question():
    out = cmds.handle_support_query(["ticket=T-1"], _FakeAgent())
    assert "Usage: support" in out


def test_support_query_server_error(monkeypatch):
    monkeypatch.setenv("JARVIS_SUPPORT_URL", "http://localhost:8080")

    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResp(400, {"error": "question must be a non-empty string"})

    monkeypatch.setattr(requests, "post", fake_post)
    out = cmds.handle_support_query(["x"], _FakeAgent())
    assert "HTTP 400" in out
    assert "non-empty" in out
