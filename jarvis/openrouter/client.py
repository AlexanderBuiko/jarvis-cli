"""
OpenRouter HTTP client.

Sends chat completion requests and returns the response text, finish reason,
latency, and the exact request/response payloads for logging and inspection.

Pricing data is fetched once from the OpenRouter model catalog on first use
and cached for the lifetime of the client. Cost fields degrade to None
silently if the catalog is unavailable.
"""

import os
import time
from typing import Any, NamedTuple

import requests

# Default model. Switched from anthropic/claude-sonnet-4 to a cheaper, fast model
# with solid function-calling — important for the long multi-server tool flow
# (many tools offered, ~8 dependent calls). Override per-session via the runtime
# `model` config; this is just the baseline when none is set.
DEFAULT_MODEL = "google/gemini-2.5-flash"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"


class Completion(NamedTuple):
    """Result of a single OpenRouter request."""
    text: str
    finish_reason: str | None
    request: dict        # exact payload sent to OpenRouter
    response: dict       # full raw response JSON from OpenRouter
    latency_ms: float    # wall-clock round-trip time in milliseconds
    # OpenAI-format tool calls the model requested this turn, or None. Present
    # only when the request offered tools and the model chose to call one; the
    # gateway's tool loop executes them and re-calls until this is empty.
    tool_calls: list[dict] | None = None


class OpenRouterClient:
    def __init__(self) -> None:
        self.api_key = self._load_api_key()
        self._pricing_cache: dict[str, tuple[float | None, float | None]] = {}
        self._context_window_cache: dict[str, int] = {}
        self._pricing_fetched = False

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
            tool_calls=self._extract_tool_calls(data),
        )

    def get_context_window(self, model_id: str) -> int | None:
        """Return the context window size (in tokens) for a model, or None."""
        if not self._pricing_fetched:
            self._fetch_pricing()
        return self._context_window_cache.get(model_id)

    def get_pricing(
        self, model_id: str
    ) -> tuple[float | None, float | None]:
        """Return (input_$/M_tokens, output_$/M_tokens) for a model.

        Returns (None, None) if pricing is unavailable. Pricing data is
        fetched once and cached for the lifetime of this client instance.
        """
        if not self._pricing_fetched:
            self._fetch_pricing()
        return self._pricing_cache.get(model_id, (None, None))

    def _build_payload(self, messages: list[dict], params: dict[str, Any]) -> dict:
        model = params.get("model") or DEFAULT_MODEL
        payload: dict = {
            "model": model,
            "messages": messages,
            # Disable automatic fallback so the recorded model always matches
            # the requested model.
            "provider": {"allow_fallbacks": False},
            # Disable OpenRouter's automatic context compression so the full
            # prompt is always sent and token counts remain accurate.
            "plugins": [{"id": "context-compression", "enabled": False}],
        }
        for field in ("temperature", "top_p", "max_tokens", "top_k", "seed"):
            if field in params and params[field] is not None:
                payload[field] = params[field]
        # Function-calling tools (injected by the gateway's tool loop). When
        # present, let the model decide whether to call one.
        if params.get("tools"):
            payload["tools"] = params["tools"]
            payload["tool_choice"] = params.get("tool_choice", "auto")
        return payload

    def _fetch_pricing(self) -> None:
        """Fetch model pricing from the OpenRouter catalog and populate the cache.

        Pricing values in the API response are dollars per token; stored values
        are dollars per million tokens for use in cost formulas.
        Failures are caught silently — cost fields will show N/A for this session.
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
                    try:
                        ctx = model.get("context_length")
                        if ctx is not None:
                            self._context_window_cache[model_id] = int(ctx)
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass  # pricing unavailable; costs will be stored as None
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
            # content is null when the model returns only tool_calls — normalise
            # to "" so callers can safely .strip() it.
            return data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected API response shape: {data}") from exc

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
