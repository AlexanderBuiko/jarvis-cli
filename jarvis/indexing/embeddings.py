"""
Embedding providers.

An ``Embedder`` Protocol with three implementations, mirroring the
``LLMEngine``/``FakeEngine`` split used elsewhere:

- ``OllamaEmbedder``     — the default. Local, free, private (the lecture's
                           recommendation). Talks to ``/api/embeddings`` on a
                           local Ollama daemon.
- ``OpenRouterEmbedder`` — opt-in cloud embedder, reusing ``OPENROUTER_API_KEY``
                           and OpenRouter's OpenAI-compatible embeddings endpoint.
                           Batched. Costs money, so it is never the default.
- ``FakeEmbedder``       — deterministic, offline. A bag-of-words vector so shared
                           vocabulary yields higher cosine similarity, which makes
                           it usable for hermetic search/pipeline tests and an
                           offline demo — not just zeros.

``make_embedder()`` is the single construction point (read from env), so the
follow-up RAG task can embed *questions* with exactly the index's configuration
without duplicating provider logic.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Protocol, runtime_checkable

import requests


@runtime_checkable
class Embedder(Protocol):
    """The contract every embedding provider satisfies."""

    provider: str
    model: str

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts, returning one vector per input (order preserved)."""
        ...

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text (e.g. a search query)."""
        ...


# ── Ollama (default, local) ──────────────────────────────────────────────────


class OllamaEmbedder:
    """Local Ollama embeddings via ``POST {url}/api/embeddings``.

    Ollama's classic endpoint embeds one ``prompt`` per call, so a batch is a
    simple loop (the volume is small — the lecture stresses RAG is tested at small
    scale). Transient failures are retried with a short linear backoff.
    """

    provider = "ollama"
    DEFAULT_MODEL = "nomic-embed-text"

    def __init__(
        self,
        model: str | None = None,
        url: str | None = None,
        timeout: int = 60,
        max_retries: int = 2,
    ) -> None:
        self.model = model or self.DEFAULT_MODEL
        self.url = (
            url or os.environ.get("JARVIS_OLLAMA_URL") or "http://localhost:11434"
        ).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    def embed_one(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def _embed(self, text: str) -> list[float]:
        last_error = "unknown error"
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    f"{self.url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    vec = resp.json().get("embedding")
                    if not vec:
                        raise RuntimeError("response had no 'embedding' field")
                    return [float(x) for x in vec]
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except requests.RequestException as exc:
                last_error = str(exc)
            if attempt < self.max_retries:
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(
            f"Ollama embedding failed at {self.url} (model '{self.model}'): "
            f"{last_error}. Is Ollama running? "
            f"Try: ollama serve  &&  ollama pull {self.model}"
        )


# ── OpenRouter (opt-in, cloud) ───────────────────────────────────────────────


class OpenRouterEmbedder:
    """Cloud embeddings via OpenRouter's OpenAI-compatible endpoint.

    Sends texts in batches (the ``input`` field accepts a list) and re-orders the
    response by its ``index`` to stay aligned with the inputs.
    """

    provider = "openrouter"
    API_URL = "https://openrouter.ai/api/v1/embeddings"
    DEFAULT_MODEL = "openai/text-embedding-3-small"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        batch_size: int = 64,
        timeout: int = 60,
        max_retries: int = 2,
    ) -> None:
        self.model = model or self.DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not self.api_key:
            raise EnvironmentError(
                "OPENROUTER_API_KEY is not set — required for the 'openrouter' "
                "embedding provider. Use the default 'ollama' provider for local, "
                "free embeddings, or set the key."
            )
        self.batch_size = max(1, batch_size)
        self.timeout = timeout
        self.max_retries = max_retries

    def embed_one(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._embed_batch(texts[i:i + self.batch_size]))
        return out

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        last_error = "unknown error"
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    self.API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self.model, "input": batch},
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data") or []
                    ordered = sorted(data, key=lambda d: d.get("index", 0))
                    vectors = [[float(x) for x in d["embedding"]] for d in ordered]
                    if len(vectors) != len(batch):
                        raise RuntimeError(
                            f"expected {len(batch)} embeddings, got {len(vectors)}"
                        )
                    return vectors
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except (requests.RequestException, KeyError, ValueError) as exc:
                last_error = str(exc)
            if attempt < self.max_retries:
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(
            f"OpenRouter embedding failed (model '{self.model}'): {last_error}"
        )


# ── Fake (tests / offline) ───────────────────────────────────────────────────


class FakeEmbedder:
    """Deterministic offline embedder — a hashed bag-of-words vector.

    No network. Texts that share words land closer in cosine space, so it gives
    believable (not random) search behaviour for hermetic tests and demos.
    """

    provider = "fake"

    def __init__(self, model: str = "fake-embed", dim: int = 64) -> None:
        self.model = model
        self.dim = dim

    def embed_one(self, text: str) -> list[float]:
        return self._vector(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in text.lower().split():
            bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.dim
            vec[bucket] += 1.0
        if not any(vec):
            vec[0] = 1.0  # never emit an all-zero vector (cosine undefined)
        return vec


# ── Factory ──────────────────────────────────────────────────────────────────


def make_embedder(
    provider: str | None = None,
    model: str | None = None,
) -> Embedder:
    """Build an embedder from explicit args or env.

    Resolution: explicit arg → ``JARVIS_EMBED_PROVIDER`` / ``JARVIS_EMBED_MODEL``
    → built-in default (``ollama`` / ``nomic-embed-text``). This is the single
    place provider selection happens, so indexing and the later RAG query path
    stay consistent.
    """
    provider = (provider or os.environ.get("JARVIS_EMBED_PROVIDER") or "ollama").lower()
    model = model or os.environ.get("JARVIS_EMBED_MODEL")
    if provider == "ollama":
        return OllamaEmbedder(model=model)
    if provider == "openrouter":
        return OpenRouterEmbedder(model=model)
    if provider == "fake":
        return FakeEmbedder(model=model or "fake-embed")
    raise ValueError(
        f"Unknown embedding provider '{provider}'. Use one of: ollama, openrouter, fake."
    )
