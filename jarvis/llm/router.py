"""
Engine selection and per-role routing.

The architecture note wants providers to be pluggable behind the LLMEngine seam.
This module is where a concrete provider is chosen and where the app decides which
engine serves which *role*:

- ``make_engine(provider)``  — build one concrete engine (cloud or local). Only the
                               selected provider is constructed, so running fully
                               local needs no OPENROUTER_API_KEY, and vice-versa.
- ``RoutingEngine``          — an LLMEngine that picks the concrete engine *per call*
                               from ``config.runtime["provider"]``. Sitting behind the
                               single main gateway, it makes ``config set provider``
                               a live toggle — the main turn switches cloud↔local
                               mid-session without touching any wiring.
- ``EngineRouter``           — builds gateways lazily and hands out the right one for a
                               role. Background roles (invariants/memory/personalization)
                               and sub-agents (pipeline stages) can each be pinned to a
                               fixed provider via env, or left to follow the main toggle.

Defaults preserve today's behaviour: with nothing set, every role uses the cloud
engine and the toggle simply flips the whole app.
"""

import logging
import os
import time
from typing import Any

import requests

from .engine import LLMEngine
from .gateway import LLMGateway
from ..openrouter.client import Completion

_gateway_log = logging.getLogger("jarvis.llm.gateway_engine")


def make_engine(provider: str | None = None) -> LLMEngine:
    """Build a concrete engine. Resolution: arg → ``JARVIS_LLM_PROVIDER`` → openrouter.

    When ``JARVIS_LLM_GATEWAY_URL`` is set, the concrete engine is wrapped in a
    ``GatewayEngine`` so EVERY model call in the app (generation, the security
    review, invariant checks) flows through the external guarded proxy — the
    Day-13/Day-14 requirement that the whole loop pass through one chokepoint.
    Opt-in: with the env unset this returns the concrete provider unchanged. The
    URL must be set only in the client process, never in the gateway server's own
    process (that would make the server call itself).
    """
    provider = (provider or os.environ.get("JARVIS_LLM_PROVIDER") or "openrouter").lower()
    gateway_url = os.environ.get("JARVIS_LLM_GATEWAY_URL", "").strip()
    if gateway_url:
        return GatewayEngine(
            gateway_url,
            downstream_provider=provider,
            model=(os.environ.get("JARVIS_LLM_GATEWAY_MODEL") or "").strip() or None,
        )
    if provider == "openrouter":
        from ..openrouter.client import OpenRouterClient
        return OpenRouterClient()
    if provider == "ollama":
        from ..ollama.client import OllamaClient
        return OllamaClient()
    raise ValueError(
        f"Unknown LLM provider '{provider}'. Use one of: openrouter, ollama."
    )


def _flatten_messages(messages: list[dict]) -> tuple[str, str]:
    """Collapse a chat ``messages[]`` into the gateway's ``(system, user)`` pair.

    The Day-13 gateway is single-shot (system + user), so multi-turn history is
    folded into one user turn. Non-user roles keep a ``[role]`` label so the model
    still sees the structure, and the whole text is what the input guard scans —
    nothing bypasses the guard. Tool/multimodal content is stringified defensively.
    """
    system_parts: list[str] = []
    user_parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        if isinstance(content, list):
            content = " ".join(str(part) for part in content)
        content = (content or "").strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        elif role == "user":
            user_parts.append(content)
        else:
            user_parts.append(f"[{role}] {content}")
    return "\n\n".join(system_parts), "\n\n".join(user_parts)


class GatewayEngine:
    """An ``LLMEngine`` that routes every call through the external LLM Gateway proxy.

    It POSTs the (flattened) prompt to the gateway's ``/v1/complete``; the gateway
    runs the input guard, forwards to the real provider, runs the output guard, and
    logs cost — so a jarvis pipeline gets the guarded chokepoint with no change to
    any caller. Two deliberate limitations in this mode: MCP tools are unavailable
    (the proxy has no tool loop, so ``tool_calls`` is always None), and per-model
    pricing is not exposed here (cost is tracked in the gateway's own audit log).
    A guard block degrades to an empty completion carrying the gateway's reason,
    rather than raising, so a blocked prompt does not crash the stage.
    """

    def __init__(
        self,
        url: str,
        *,
        downstream_provider: str,
        model: str | None = None,
        timeout: float = 180.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._downstream = downstream_provider
        self._model = model
        self._timeout = timeout

    def complete(self, messages: list[dict], params: dict[str, Any]) -> Completion:
        system, user = _flatten_messages(messages)
        payload: dict[str, Any] = {"system": system, "user": user, "provider": self._downstream}
        # Only forward an explicit gateway model; the app's runtime model default is
        # a cloud id that would be wrong for a local downstream, so let the gateway
        # pick its provider default unless JARVIS_LLM_GATEWAY_MODEL is set.
        if self._model:
            payload["model"] = self._model

        t0 = time.perf_counter()
        resp = requests.post(f"{self._url}/v1/complete", json=payload, timeout=self._timeout)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        try:
            data = resp.json()
        except ValueError:
            data = {}

        if resp.status_code == 400:
            # Input guard refused the prompt. Degrade to an empty result; the block
            # itself is recorded in the gateway's audit log.
            _gateway_log.warning("gateway blocked a prompt: %s", data.get("reason") or data.get("error"))
            return Completion(text="", finish_reason="content_filter", request=payload,
                              response={"gateway": data}, latency_ms=latency_ms)
        if resp.status_code != 200:
            raise RuntimeError(f"gateway error {resp.status_code}: {data.get('error') or data}")

        text = "" if data.get("blocked") else (data.get("text") or "")
        response = {
            "model": data.get("model"),
            "usage": data.get("usage") or {},
            # keep the guard verdict so callers/logs can see what the gateway did
            "gateway": {k: data.get(k) for k in (
                "input_action", "output_action", "input_findings", "output_findings",
                "blocked", "reason", "cost_usd",
            )},
        }
        return Completion(text=text, finish_reason="stop", request=payload,
                          response=response, latency_ms=latency_ms, tool_calls=None)

    def get_pricing(self, model_id: str) -> tuple[float | None, float | None]:
        return (None, None)  # cost is tracked at the gateway, not re-derived here

    def get_context_window(self, model_id: str) -> int | None:
        return None


def current_provider(config: Any) -> str:
    """The provider the main turn should use right now (live-readable)."""
    runtime = getattr(config, "runtime", {}) or {}
    return (runtime.get("provider") or os.environ.get("JARVIS_LLM_PROVIDER") or "openrouter").lower()


class RoutingEngine:
    """An LLMEngine that delegates to the currently-selected concrete engine.

    Reads the provider fresh on every call, so a runtime ``config set provider``
    takes effect on the next turn with no restart. Concrete engines are built once
    and cached by the router.
    """

    def __init__(self, config: Any, router: "EngineRouter") -> None:
        self._config = config
        self._router = router

    def _engine(self) -> LLMEngine:
        return self._router.engine(current_provider(self._config))

    def complete(self, messages: list[dict], params: dict[str, Any]) -> Completion:
        return self._engine().complete(messages, params)

    def get_pricing(self, model_id: str) -> tuple[float | None, float | None]:
        return self._engine().get_pricing(model_id)

    def get_context_window(self, model_id: str) -> int | None:
        return self._engine().get_context_window(model_id)


class EngineRouter:
    """Owns the engines/gateways and resolves the right gateway per role.

    - ``main_gateway`` follows the live ``provider`` toggle.
    - ``role_gateway(env_var)`` pins a role to a provider named in ``env_var``; when
      that env var is unset the role shares ``main_gateway`` and thus follows the
      toggle too.
    """

    def __init__(
        self,
        config: Any,
        tool_provider: Any | None = None,
        tool_gate: Any | None = None,
    ) -> None:
        self._config = config
        self._tool_provider = tool_provider
        # Permission gate for mutating tool calls, attached to every gateway this router
        # hands out (so the main turn and any pinned provider both honour it).
        self._tool_gate = tool_gate
        self._engines: dict[str, LLMEngine] = {}
        self._provider_gateways: dict[str, LLMGateway] = {}
        self._main_gateway: LLMGateway | None = None

    def engine(self, provider: str) -> LLMEngine:
        """Lazily build and cache the concrete engine for a provider."""
        if provider not in self._engines:
            self._engines[provider] = make_engine(provider)
        return self._engines[provider]

    @property
    def main_gateway(self) -> LLMGateway:
        """The single gateway for the main turn — wraps the live-routing engine."""
        if self._main_gateway is None:
            self._main_gateway = LLMGateway(
                RoutingEngine(self._config, self),
                tool_provider=self._tool_provider,
                tool_gate=self._tool_gate,
            )
        return self._main_gateway

    def provider_gateway(self, provider: str) -> LLMGateway:
        """A gateway pinned to one concrete provider (cached)."""
        if provider not in self._provider_gateways:
            self._provider_gateways[provider] = LLMGateway(
                self.engine(provider),
                tool_provider=self._tool_provider,
                tool_gate=self._tool_gate,
            )
        return self._provider_gateways[provider]

    def role_gateway(self, env_var: str) -> LLMGateway:
        """Resolve a role's gateway: env pins a provider, else follow the main toggle."""
        pinned = (os.environ.get(env_var) or "").strip().lower()
        if not pinned:
            return self.main_gateway
        return self.provider_gateway(pinned)
