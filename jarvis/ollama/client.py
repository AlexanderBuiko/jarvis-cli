"""
Local Ollama chat client — a concrete LLMEngine, free and private.

This is the local counterpart to OpenRouterClient (the cloud engine). The lecture's
whole point: a local LLM is the same kind of model, just running on your own machine
— free, private, no internet. It plugs into the exact same LLMEngine seam, so the
gateway, the agent and every stage-agent talk to it without knowing the difference.

Ollama exposes an OpenAI-compatible endpoint at ``/v1/chat/completions``, so the
response shape (``choices`` / ``usage`` / ``model`` / ``tool_calls``) matches what
``accounting.make_call_record`` already parses — no special-casing downstream.

Pricing is (0.0, 0.0): local inference costs no tokens, so cost fields report $0.00
(the accounting math already handles a zero rate). Context window is read once from
``/api/show``.
"""

import os
import time
from typing import Any

import requests

from ..openrouter.client import Completion

# The model this engine defaults to when the request doesn't name a *local* one.
# Overridable via JARVIS_OLLAMA_MODEL. Pulled with: ollama pull qwen2.5:7b
DEFAULT_MODEL = "qwen2.5:7b"


class OllamaClient:
    """Talks to a local Ollama daemon's OpenAI-compatible chat endpoint.

    Satisfies the ``LLMEngine`` Protocol structurally (``complete`` /
    ``get_pricing`` / ``get_context_window``), so it drops into the same gateway
    seam as ``OpenRouterClient``.
    """

    def __init__(
        self,
        model: str | None = None,
        url: str | None = None,
        timeout: int = 120,
    ) -> None:
        # JARVIS_OLLAMA_URL is shared with the embedder, so a single setting moves
        # both chat and embeddings to the same daemon (e.g. a LAN Mac Studio).
        self.default_model = model or os.environ.get("JARVIS_OLLAMA_MODEL") or DEFAULT_MODEL
        self.url = (
            url or os.environ.get("JARVIS_OLLAMA_URL") or "http://localhost:11434"
        ).rstrip("/")
        self.timeout = timeout
        # Optional X-API-Key sent on every call. Lets the CLI talk to an
        # authenticated remote LLM service (the jarvis-mcp-server chat proxy) rather
        # than only a bare local daemon. Unset → no header (plain local Ollama).
        self.api_key = (os.environ.get("JARVIS_OLLAMA_API_KEY") or "").strip()
        self._context_window_cache: dict[str, int | None] = {}

    def _headers(self) -> dict:
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def complete(
        self,
        messages: list[dict],
        params: dict[str, Any],
    ) -> Completion:
        """Send messages and return a Completion with the full request and response."""
        payload = self._build_payload(messages, params)
        t0 = time.perf_counter()
        try:
            response = requests.post(
                f"{self.url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(self._unreachable_message(exc)) from exc
        latency_ms = (time.perf_counter() - t0) * 1000
        self._raise_for_status(response)
        data = response.json()
        return Completion(
            text=self._extract_text(data),
            finish_reason=self._extract_finish_reason(data),
            request=payload,
            response=data,
            latency_ms=latency_ms,
            tool_calls=self._extract_tool_calls(data),
        )

    def get_pricing(self, model_id: str) -> tuple[float | None, float | None]:
        """Local inference is free — a zero rate, so every call records $0.00."""
        return (0.0, 0.0)

    def get_context_window(self, model_id: str) -> int | None:
        """Return the model's context window, read once from ``/api/show``."""
        model_id = self._resolve_model(model_id)
        if model_id in self._context_window_cache:
            return self._context_window_cache[model_id]
        ctx = self._fetch_context_window(model_id)
        self._context_window_cache[model_id] = ctx
        return ctx

    # ── payload / model resolution ──────────────────────────────────────────────

    def _build_payload(self, messages: list[dict], params: dict[str, Any]) -> dict:
        payload: dict = {
            "model": self._resolve_model(params.get("model")),
            "messages": messages,
        }
        for field in ("temperature", "top_p", "max_tokens", "top_k", "seed"):
            if field in params and params[field] is not None:
                payload[field] = params[field]
        if params.get("tools"):
            payload["tools"] = params["tools"]
            payload["tool_choice"] = params.get("tool_choice", "auto")
        return payload

    def _resolve_model(self, requested: str | None) -> str:
        """Pick the model to run.

        A cloud model id (``vendor/model``, always slash-bearing) is meaningless to
        Ollama — it means a live toggle from cloud→local carried the cloud model
        through. In that case fall back to this engine's own local default. A local
        tag (no slash, e.g. ``qwen2.5:7b``) is honoured so the user can still pick a
        specific pulled model.
        """
        if requested and "/" not in requested:
            return requested
        return self.default_model

    def _fetch_context_window(self, model_id: str) -> int | None:
        try:
            resp = requests.post(
                f"{self.url}/api/show", json={"name": model_id},
                headers=self._headers(), timeout=10
            )
            if resp.status_code != 200:
                return None
            info = resp.json().get("model_info") or {}
            # Key is architecture-scoped, e.g. "qwen2.context_length".
            for key, value in info.items():
                if key.endswith(".context_length"):
                    return int(value)
        except (requests.RequestException, ValueError, TypeError):
            return None
        return None

    def _unreachable_message(self, exc: Exception) -> str:
        return (
            f"Ollama is not reachable at {self.url} ({exc}). "
            f"Start it and pull the model:\n"
            f"  ollama serve  &&  ollama pull {self.default_model}"
        )

    # ── response extraction (OpenAI-compatible shape) ───────────────────────────

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.status_code != 200:
            try:
                detail = response.json().get("error", {})
                detail = detail.get("message", response.text) if isinstance(detail, dict) else response.text
            except Exception:
                detail = response.text
            raise RuntimeError(f"Ollama API error {response.status_code}: {detail}")

    @staticmethod
    def _extract_text(data: dict) -> str:
        try:
            return data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected Ollama response shape: {data}") from exc

    @staticmethod
    def _extract_tool_calls(data: dict) -> list[dict] | None:
        try:
            return data["choices"][0]["message"].get("tool_calls") or None
        except (KeyError, IndexError):
            return None

    @staticmethod
    def _extract_finish_reason(data: dict) -> str | None:
        try:
            return data["choices"][0].get("finish_reason")
        except (KeyError, IndexError):
            return None
