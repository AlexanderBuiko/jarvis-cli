"""Tests for the WebAdapter's browser-free parts (jarvis/smoke/web.py).

The full drive-the-browser path is an integration test run by
`python -m jarvis.smoke --platform web` (it needs Playwright + a browser binary),
so it is out of scope for the unit suite. What is unit-testable here: the adapter
satisfies the SmokeAdapter contract, picks a real free port, and — when Playwright
is absent — fails with a clear install hint rather than an opaque ImportError.
"""

import builtins

from jarvis.smoke.adapter import SmokeAdapter
from jarvis.smoke.web import WebAdapter, _free_port


def test_web_adapter_satisfies_the_protocol():
    assert isinstance(WebAdapter(), SmokeAdapter)


def test_free_port_is_a_usable_port_number():
    port = _free_port()
    assert isinstance(port, int)
    assert 1024 < port < 65536


def test_open_without_playwright_raises_a_clear_install_hint(monkeypatch):
    real_import = builtins.__import__

    def no_playwright(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_playwright)
    adapter = WebAdapter()
    try:
        adapter.open()
        raised = None
    except RuntimeError as exc:
        raised = str(exc)
    assert raised is not None
    assert "playwright install chromium" in raised


def test_close_is_safe_before_open():
    # No process, no browser — close must not raise.
    WebAdapter().close()
