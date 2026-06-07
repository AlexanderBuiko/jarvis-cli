"""
OpenRouter client.

Sends chat completion requests to OpenRouter using the requests library.
No streaming. No function calling. Model is configurable via params.
"""

import time
import os
from typing import Any, NamedTuple

import requests

DEFAULT_MODEL = "anthropic/claude-sonnet-4"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"


class Completion(NamedTuple):
    """Result of a single OpenRouter call."""
    text: str
    finish_reason: str | None
    request: dict   # exact payload sent to OpenRouter
    response: dict  # full raw response JSON from OpenRouter
    latency_ms: float


class OpenRouterClient:
    def __init__(self) -> None:
        self.api_key = self._load_api_key()
        self._pricing_cache: dict[str, tuple[float | None, float | None]] = {}
        self._pricing_fetched = False

    # ── Public API ────────────────────────────────────────────────────────────

    def complete(
        self,
        messages: list[dict],
        params: dict[str, Any],
    ) -> Completion:
        """Send messages and return a Completion including latency_ms."""
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

    def get_pricing(
        self, model_id: str
    ) -> tuple[float | None, float | None]:
        """Return (input_price_per_million_usd, output_price_per_million_usd).

        Returns (None, None) if pricing is unavailable for the given model.
        Pricing data is fetched once and cached for the lifetime of this client.
        """
        if not self._pricing_fetched:
            self._fetch_pricing()
        return self._pricing_cache.get(model_id, (None, None))

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_payload(self, messages: list[dict], params: dict[str, Any]) -> dict:
        """Build the OpenRouter request dict.

        Exactly the fields present in *params* are considered; nothing else can
        leak into the payload regardless of any global or persisted state.
        """
        model = params.get("model") or DEFAULT_MODEL
        payload: dict = {
            "model": model,
            "messages": messages,
            # Disable automatic fallback to a different model or provider.
            # If the requested model is unavailable, OpenRouter returns an error
            # instead of silently routing the request elsewhere.  This is required
            # for benchmark accuracy: recorded model, latency, and cost must
            # correspond exactly to the model that was requested.
            "provider": {"allow_fallbacks": False},
        }

        # Scalar sampling params — included when present in the runtime config
        # (either from the mode's preset defaults or user overrides).
        for field in ("temperature", "top_p", "max_tokens", "top_k", "seed"):
            if field in params and params[field] is not None:
                payload[field] = params[field]

        # Stop sequence — sent when api_stop_enabled is true.
        if params.get("api_stop_enabled") and "stop_sequence" in params:
            payload["stop"] = [params["stop_sequence"]]

        return payload

    def _fetch_pricing(self) -> None:
        """Fetch model pricing from OpenRouter and populate the cache.

        Pricing values in the API response are dollars per token; we store
        them as dollars per million tokens for readability in cost formulas.
        """
        try:
            response = requests.get(MODELS_URL, headers=self._headers(), timeout=10)
            if response.status_code == 200:
                for model in response.json().get("data", []):
                    model_id = model.get("id")
                    if not model_id:
                        continue
                    pricing = model.get("pricing", {})
                    try:
                        input_per_m = float(pricing["prompt"]) * 1_000_000
                        output_per_m = float(pricing["completion"]) * 1_000_000
                        self._pricing_cache[model_id] = (input_per_m, output_per_m)
                    except (KeyError, ValueError, TypeError):
                        self._pricing_cache[model_id] = (None, None)
        except Exception:
            pass  # pricing unavailable; costs will be stored as null
        finally:
            self._pricing_fetched = True

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
