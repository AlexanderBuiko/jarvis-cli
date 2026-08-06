"""
LLM core server — jarvis's model layer behind a small HTTP endpoint.

Week-10 (Security). The security stack splits into three tiers: the application,
the guarded gateway, and this — the LLM core. Extracting the core behind HTTP lets
the gateway hold only security concerns (guards, audit, rate limit) with no LLM SDK
of its own, and lets any caller reach the same *metered* ``LLMGateway`` over the
network. The accounting is the one jarvis already does in-process
(``LLMGateway.record`` → real cost from cached pricing, $0 for local Ollama),
exposed here as ``POST /v1/complete``.

``LLMCore.handle_complete`` takes a parsed body and returns ``(status, dict)`` with
no socket in sight, so the core is testable without binding a port — the same shape
the sibling gateway uses. The transport is stdlib ``http.server``: jarvis is
stdlib-first and a single-shot completion endpoint needs nothing heavier.

This process must **not** have ``JARVIS_LLM_GATEWAY_URL`` set. The core talks
straight to the provider; pointing it back at a gateway that forwards here would
loop forever.
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from ..llm.gateway import LLMGateway
from ..llm.router import make_engine

logger = logging.getLogger("jarvis.serve")


def complete_one(system: str, user: str, *, provider: str, model: str | None = None,
                 temperature: float = 0.1, max_tokens: int = 700) -> dict:
    """Run one metered completion and return the JSON body the gateway forwards.

    This is the body of flat-hunter's old ``complete_metered``, moved into jarvis so
    the core owns its own accounting: ``LLMGateway.record`` builds a self-contained
    call record (usage + cost from the engine's cached pricing) instead of estimating.
    """
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    params: dict[str, Any] = {"temperature": temperature, "max_tokens": max_tokens}
    if model:
        params["model"] = model
    gateway = LLMGateway(make_engine(provider))
    completion = gateway.complete(messages, params, label="llm-core")
    record = gateway.record(1, "llm-core", completion)
    usage = record["response"].get("usage") or {}
    return {
        "text": completion.text.strip(),
        "model": record["response"].get("model"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cost_usd": record["cost"].get("total_usd"),
        "latency_ms": completion.latency_ms,
    }


class LLMCore:
    """Runs one completion end to end; ``handle_complete`` returns ``(status, dict)``.

    ``complete_fn`` is injectable so a test can fake the provider without a network
    call — the same seam the gateway exposes for the same reason.
    """

    def __init__(self, *, default_provider: str = "ollama",
                 complete_fn: Callable[..., dict] | None = None) -> None:
        self.default_provider = default_provider
        self._complete = complete_fn or complete_one

    def handle_complete(self, body: dict[str, Any]) -> tuple[int, dict]:
        user = body.get("user")
        if not isinstance(user, str) or not user.strip():
            return 400, {"error": "field 'user' (string) is required"}
        system = body.get("system") or ""
        provider = body.get("provider") or self.default_provider
        model = body.get("model")
        try:
            return 200, self._complete(system, user, provider=provider, model=model)
        except Exception as exc:  # noqa: BLE001 — report as 502, never crash the core
            logger.warning("provider call failed: %s", exc)
            return 502, {"error": f"provider call failed: {exc}"}


# ── HTTP translation layer ────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    """Thin adapter: parse the request, call ``LLMCore``, write JSON back."""

    protocol_version = "HTTP/1.1"

    @property
    def _app(self) -> LLMCore:
        return self.server.app  # type: ignore[attr-defined]

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — stdlib-mandated name
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/complete":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            self._send(400, {"error": f"invalid JSON body: {exc}"})
            return
        status, payload = self._app.handle_complete(body)
        self._send(status, payload)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)


def build_server(host: str, port: int, app: LLMCore) -> ThreadingHTTPServer:
    """Create (but do not serve) the HTTP server bound to ``host:port``."""
    server = ThreadingHTTPServer((host, port), _Handler)
    server.app = app  # type: ignore[attr-defined]
    return server


def core_from_env() -> LLMCore:
    """Build an ``LLMCore`` from ``JARVIS_LLM_PROVIDER``."""
    return LLMCore(default_provider=os.environ.get("JARVIS_LLM_PROVIDER", "ollama"))
