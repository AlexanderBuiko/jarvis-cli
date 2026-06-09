"""
OpenRouter HTTP client.

Sends chat completion requests and returns the response text, finish reason,
latency, and the exact request/response payloads for logging and inspection.
"""

import os
import time
from typing import Any, NamedTuple

import requests

DEFAULT_MODEL = "anthropic/claude-sonnet-4"
API_URL = "https://openrouter.ai/api/v1/chat/completions"


class Completion(NamedTuple):
    """Result of a single OpenRouter request."""
    text: str
    finish_reason: str | None
    request: dict        # exact payload sent to OpenRouter
    response: dict       # full raw response JSON from OpenRouter
    latency_ms: float    # wall-clock round-trip time in milliseconds


class OpenRouterClient:
    def __init__(self) -> None:
        self.api_key = self._load_api_key()

    def complete(
        self,
        messages: list[dict],
        params: dict[str, Any],
    ) -> Completion:
        """Send messages and return a Completion with the full request and response."""
        payload = self._build_payload(messages, params)
        t0 = time.perf_counter()
        response = requests.post(
            API_URL,
            headers=self._headers(),
            json=payload,
            timeout=60,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        self._raise_for_status(response)
        data = response.json()
        return Completion(
            text=self._extract_text(data),
            finish_reason=self._extract_finish_reason(data),
            request=payload,
            response=data,
            latency_ms=latency_ms,
        )

    def _build_payload(self, messages: list[dict], params: dict[str, Any]) -> dict:
        model = params.get("model") or DEFAULT_MODEL
        payload: dict = {
            "model": model,
            "messages": messages,
            # Disable automatic fallback so the recorded model always matches
            # the requested model.
            "provider": {"allow_fallbacks": False},
        }
        for field in ("temperature", "top_p", "max_tokens", "top_k", "seed"):
            if field in params and params[field] is not None:
                payload[field] = params[field]
        return payload

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jarvis-cli",
            "X-Title": "Jarvis CLI",
        }

    @staticmethod
    def _load_api_key() -> str:
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise EnvironmentError(
                "OPENROUTER_API_KEY environment variable is not set.\n"
                "Export it before running Jarvis:\n\n"
                "  export OPENROUTER_API_KEY=your_key_here"
            )
        return key

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.status_code != 200:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise RuntimeError(
                f"OpenRouter API error {response.status_code}: {detail}"
            )

    @staticmethod
    def _extract_text(data: dict) -> str:
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected API response shape: {data}") from exc

    @staticmethod
    def _extract_finish_reason(data: dict) -> str | None:
        try:
            return data["choices"][0].get("finish_reason")
        except (KeyError, IndexError):
            return None
