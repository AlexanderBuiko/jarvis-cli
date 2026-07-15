"""Tests for the CLI `/help` thin client (jarvis/repl/commands.py)."""

import requests

import jarvis.repl.commands as cmds


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeProvider:
    def __init__(self, branch="main"):
        self._branch = branch

    def call_tool(self, name, args):
        assert name == "git.get_current_branch"
        return self._branch


class _FakeAgent:
    def __init__(self, provider=None):
        self.tool_provider = provider


def test_help_endpoint_derives_from_mcp_url(monkeypatch):
    monkeypatch.delenv("JARVIS_HELP_URL", raising=False)
    monkeypatch.setenv("JARVIS_MCP_URL", "http://host:8080/mcp")
    endpoint, error = cmds._help_endpoint()
    assert error is None
    assert endpoint == "http://host:8080/help"


def test_help_endpoint_missing_url(monkeypatch):
    for var in ("JARVIS_HELP_URL", "JARVIS_MCP_URL", "JARVIS_TIME_MCP_URL"):
        monkeypatch.delenv(var, raising=False)
    endpoint, error = cmds._help_endpoint()
    assert endpoint is None
    assert "server URL" in error


def test_help_query_renders_answer_with_branch(monkeypatch):
    monkeypatch.setenv("JARVIS_HELP_URL", "http://localhost:8080")

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp(200, {"answer": "Grounded answer.", "notice": "grounded in 3 excerpt(s)"})

    monkeypatch.setattr(requests, "post", fake_post)

    out = cmds.handle_help_query("how does chunking work?", _FakeAgent(_FakeProvider("main")))

    assert captured["url"] == "http://localhost:8080/help"
    assert captured["json"]["branch"] == "main"
    assert captured["json"]["question"] == "how does chunking work?"
    assert "Grounded answer." in out
    assert "branch: main" in out


def test_help_query_server_error(monkeypatch):
    monkeypatch.setenv("JARVIS_HELP_URL", "http://localhost:8080")

    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResp(400, {"error": "question must be a non-empty string"})

    monkeypatch.setattr(requests, "post", fake_post)
    out = cmds.handle_help_query("x", _FakeAgent(None))
    assert "HTTP 400" in out
    assert "non-empty" in out


def test_help_query_unreachable(monkeypatch):
    monkeypatch.setenv("JARVIS_HELP_URL", "http://localhost:8080")

    def fake_post(url, json=None, headers=None, timeout=None):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(requests, "post", fake_post)
    out = cmds.handle_help_query("x", _FakeAgent(None))
    assert "unreachable" in out
