"""
Document indexing pipeline.

Loads a collection of text documents, splits them into chunks (fixed-size or
structure-aware), embeds the chunks (Ollama by default, OpenRouter optionally),
and stores a local JSON index of (embedding, chunk text, metadata).

The pieces mirror the rest of the codebase: an ``Embedder`` Protocol with swappable
implementations and a test fake (like ``LLMEngine``/``FakeEngine``), and JSON
persistence under ``~/.jarvis`` (like the thread/task stores). The search seam,
self-describing index header, and reusable embedder factory are deliberately in
place so the follow-up RAG task (question → retrieve → merge → generate) plugs in
without rework.
"""

from .loader import Document, load_documents
from .chunking import Chunk, CHUNKERS, fixed_size_chunks, structure_aware_chunks
from .embeddings import (
    Embedder,
    OllamaEmbedder,
    OpenRouterEmbedder,
    FakeEmbedder,
    make_embedder,
)
from .store import IndexStore, normalize, cosine_top_k
from .pipeline import IndexPipeline, BuildResult

__all__ = [
    "Document",
    "load_documents",
    "Chunk",
    "CHUNKERS",
    "fixed_size_chunks",
    "structure_aware_chunks",
    "Embedder",
    "OllamaEmbedder",
    "OpenRouterEmbedder",
    "FakeEmbedder",
    "make_embedder",
    "IndexStore",
    "normalize",
    "cosine_top_k",
    "IndexPipeline",
    "BuildResult",
]
