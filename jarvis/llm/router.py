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

import os
from typing import Any

from .engine import LLMEngine
from .gateway import LLMGateway
from ..openrouter.client import Completion


def make_engine(provider: str | None = None) -> LLMEngine:
    """Build a concrete engine. Resolution: arg → ``JARVIS_LLM_PROVIDER`` → openrouter."""
    provider = (provider or os.environ.get("JARVIS_LLM_PROVIDER") or "openrouter").lower()
    if provider == "openrouter":
        from ..openrouter.client import OpenRouterClient
        return OpenRouterClient()
    if provider == "ollama":
        from ..ollama.client import OllamaClient
        return OllamaClient()
    raise ValueError(
        f"Unknown LLM provider '{provider}'. Use one of: openrouter, ollama."
    )


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

    def __init__(self, config: Any, tool_provider: Any | None = None) -> None:
        self._config = config
        self._tool_provider = tool_provider
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
                RoutingEngine(self._config, self), tool_provider=self._tool_provider
            )
        return self._main_gateway

    def provider_gateway(self, provider: str) -> LLMGateway:
        """A gateway pinned to one concrete provider (cached)."""
        if provider not in self._provider_gateways:
            self._provider_gateways[provider] = LLMGateway(
                self.engine(provider), tool_provider=self._tool_provider
            )
        return self._provider_gateways[provider]

    def role_gateway(self, env_var: str) -> LLMGateway:
        """Resolve a role's gateway: env pins a provider, else follow the main toggle."""
        pinned = (os.environ.get(env_var) or "").strip().lower()
        if not pinned:
            return self.main_gateway
        return self.provider_gateway(pinned)
