"""Tests for the web backend command routing (jarvis/web/server.py).

The browser-driven happy path is exercised live via the Browser MCP (see the web
smoke report); here the routing guard is tested without a socket or a browser.
What matters: only the allowed command families reach _dispatch, and a disallowed
or failing command degrades to a readable string instead of hanging or crashing
the server.
"""

import jarvis.web.server as server
from jarvis.web.server import run_command


class _Recorder:
    """Captures the _dispatch call so the test can assert routing happened."""

    def __init__(self, reply="ok"):
        self.reply = reply
        self.called_with = None

    def __call__(self, command, agent, config, controller):
        self.called_with = command
        return self.reply


def test_a_disallowed_command_never_reaches_dispatch(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr("jarvis.repl.loop._dispatch", rec)
    out = run_command("rag ask something", agent=None, config=None, controller=None)
    assert "not available in the web UI" in out
    assert rec.called_with is None            # guard blocked it before dispatch


def test_an_allowed_command_is_routed_to_dispatch(monkeypatch):
    rec = _Recorder(reply="temperature = 0.7")
    monkeypatch.setattr("jarvis.repl.loop._dispatch", rec)
    out = run_command("config set temperature 0.7", agent=None, config=None, controller=None)
    assert out == "temperature = 0.7"
    assert rec.called_with == "config set temperature 0.7"


def test_an_empty_command_is_rejected():
    assert "not available" in run_command("", agent=None, config=None, controller=None)


def test_a_handler_exception_degrades_to_an_error_string(monkeypatch):
    def boom(*_a, **_k):
        raise ValueError("kaboom")
    monkeypatch.setattr("jarvis.repl.loop._dispatch", boom)
    out = run_command("config show", agent=None, config=None, controller=None)
    assert out.startswith("error:")
    assert "kaboom" in out


def test_exit_is_disabled(monkeypatch):
    def bye(*_a, **_k):
        raise SystemExit(0)
    monkeypatch.setattr("jarvis.repl.loop._dispatch", bye)
    out = run_command("config show", agent=None, config=None, controller=None)
    assert "exit is disabled" in out


def test_only_the_intended_families_are_allowed():
    assert server._ALLOWED == {"config", "task", "thread", "invariants", "help"}
