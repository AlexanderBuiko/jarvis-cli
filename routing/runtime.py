"""Build the two model tiers the router escalates between.

The router depends only on the ``LLMEngine`` Protocol, so this is the one place
that names concrete clients and model ids. Imports are function-local on purpose:
constructing ``OpenRouterClient`` loads the API key eagerly and raises when it is
missing, so importing this module must not require any key — the cost is paid only
when you actually ask to build the cloud tiers.

Default is **two local Ollama models**: a small-parameter model that escalates to
a bigger one. Both run through a single ``OllamaClient`` — the per-call ``model``
tag selects the size, so no second client is needed. Pass ``local=False`` to route
between two OpenRouter models instead (still no OpenAI: the ids are served through
OpenRouter).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.llm.engine import LLMEngine

# Local default: same family, same instruct tuning, a pure parameter gap. Both are
# already-common pulls; override with --cheap-model / --strong-model.
_LOCAL_CHEAP = "qwen2.5:3b"
_LOCAL_STRONG = "qwen2.5:7b"
# Cloud default: a small model escalating to a strong one, both via OpenRouter.
_CLOUD_CHEAP = "openai/gpt-4o-mini"
_CLOUD_STRONG = "anthropic/claude-3.5-sonnet"


@dataclass
class Tier:
    name: str          # "cheap" | "strong" — the label used in the report
    engine: LLMEngine  # concrete engine serving this tier
    model: str         # model id, passed as params["model"]


@dataclass
class Tiers:
    cheap: Tier   # tried first on every query
    strong: Tier  # the escalation target when the cheap answer is uncertain


def build_tiers(local: bool = True, cheap_model: str | None = None,
                strong_model: str | None = None) -> Tiers:
    """Return the ``(cheap, strong)`` tier pair for local Ollama or cloud OpenRouter."""
    if local:
        from jarvis.ollama.client import OllamaClient
        engine = OllamaClient()  # one client; the per-call model tag picks the size
        return Tiers(
            cheap=Tier("cheap", engine, cheap_model or _LOCAL_CHEAP),
            strong=Tier("strong", engine, strong_model or _LOCAL_STRONG),
        )
    from jarvis.openrouter.client import OpenRouterClient
    engine = OpenRouterClient()
    return Tiers(
        cheap=Tier("cheap", engine, cheap_model or _CLOUD_CHEAP),
        strong=Tier("strong", engine, strong_model or _CLOUD_STRONG),
    )
