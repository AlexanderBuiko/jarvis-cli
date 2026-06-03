"""
OpenRouter client.

Sends chat completion requests to OpenRouter using the requests library.
No streaming. No function calling. One hardcoded model.
"""

import os
import requests

from ..config.schema import JarvisConfig

MODEL = "anthropic/claude-sonnet-4"
API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterClient:
    def __init__(self):
        self.api_key = self._load_api_key()

    # ── Public API ────────────────────────────────────────────────────────────

    def complete(
        self,
        messages: list[dict],
        cfg: JarvisConfig,
    ) -> tuple[str, str | None]:
        """Send messages and return (reply_text, finish_reason)."""
        payload = self._build_payload(messages, cfg)
        response = requests.post(
            API_URL,
            headers=self._headers(),
            json=payload,
            timeout=60,
        )
        self._raise_for_status(response)
        data = response.json()
        return self._extract_text(data), self._extract_finish_reason(data)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_payload(self, messages: list[dict], cfg: JarvisConfig) -> dict:
        use_api_controls = cfg.control_mode in ("api", "both")

        payload: dict = {
            "model": MODEL,
            "messages": messages,
        }

        if use_api_controls:
            payload["temperature"] = cfg.temperature
            payload["top_p"] = cfg.top_p
            payload["max_tokens"] = cfg.max_tokens

            # top_k and seed are not standard OpenAI params but OpenRouter
            # passes them through to Anthropic models.
            if cfg.top_k is not None:
                payload["top_k"] = cfg.top_k
            if cfg.seed is not None:
                payload["seed"] = cfg.seed

            if cfg.api_stop_enabled:
                payload["stop"] = [cfg.stop_sequence]

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
