"""
Indexing pipeline.

Ties the pieces together: load → chunk → embed → store, plus ``search`` over a
stored index and ``compare`` of the two chunking strategies. The pipeline depends
only on the ``Embedder`` Protocol and ``IndexStore``, so tests drive it with
``FakeEmbedder`` and a temp directory.

``search`` returns scored records with full metadata (not bare strings) so the
follow-up RAG task can both build a cited context block and score which sources
were retrieved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .chunking import CHUNKERS, Chunk, DEFAULT_OVERLAP, DEFAULT_SIZE
from .embeddings import Embedder
from .loader import load_documents
from .store import IndexStore, cosine_top_k, normalize


@dataclass
class BuildResult:
    name: str
    provider: str
    model: str
    dim: int
    strategy: str
    size: int
    overlap: int
    n_documents: int
    n_chunks: int
    path: str


@dataclass
class StrategyStats:
    """Per-strategy summary produced by ``compare``."""

    strategy: str
    n_chunks: int
    avg_chars: int
    min_chars: int
    max_chars: int
    # Top hit per strategy when compare() is given a query: (score, source, section).
    top_hits: list[tuple[float, str, str]] = field(default_factory=list)


class IndexPipeline:
    def __init__(self, embedder: Embedder, store: IndexStore | None = None) -> None:
        self._embedder = embedder
        self._store = store or IndexStore()

    def build(
        self,
        path: str | Path,
        name: str,
        *,
        strategy: str = "structure",
        size: int = DEFAULT_SIZE,
        overlap: int = DEFAULT_OVERLAP,
    ) -> BuildResult:
        """Load, chunk, embed, and store an index. Returns a summary."""
        if strategy not in CHUNKERS:
            raise ValueError(
                f"Unknown strategy '{strategy}'. Use one of: {', '.join(CHUNKERS)}."
            )
        docs = load_documents(path)
        if not docs:
            raise ValueError(f"No indexable documents found at: {path}")

        chunker = CHUNKERS[strategy]
        chunks: list[Chunk] = []
        for doc in docs:
            chunks.extend(chunker(doc, size=size, overlap=overlap))
        if not chunks:
            raise ValueError("Documents produced no chunks (all empty?).")

        vectors = self._embedder.embed_batch([c.text for c in chunks])
        dim = len(vectors[0]) if vectors else 0

        records = [
            {
                "chunk_id": c.metadata["chunk_id"],
                "text": c.text,
                "embedding": vec,
                "metadata": c.metadata,
            }
            for c, vec in zip(chunks, vectors)
        ]
        header = {
            "provider": self._embedder.provider,
            "model": self._embedder.model,
            "dim": dim,
            "strategy": strategy,
            "size": size,
            "overlap": overlap,
            "n_documents": len(docs),
            "n_chunks": len(chunks),
            "sources": [d.source for d in docs],
        }
        stored_path = self._store.save(name, header, records)
        return BuildResult(
            name=name,
            provider=self._embedder.provider,
            model=self._embedder.model,
            dim=dim,
            strategy=strategy,
            size=size,
            overlap=overlap,
            n_documents=len(docs),
            n_chunks=len(chunks),
            path=str(stored_path),
        )

    def search(self, name: str, query: str, k: int = 5) -> list[dict]:
        """Embed ``query`` and return the top-k matching records from an index."""
        query_vector = self._embedder.embed_one(query)
        return self._store.search(name, query_vector, k)

    def compare(
        self,
        path: str | Path,
        *,
        size: int = DEFAULT_SIZE,
        overlap: int = DEFAULT_OVERLAP,
        query: str | None = None,
        k: int = 3,
    ) -> list[StrategyStats]:
        """Chunk the same corpus both ways and report comparative stats.

        Self-contained and side-effect-free: it chunks (and, if ``query`` is
        given, embeds + searches) in memory without writing any index, so it's
        purely a measurement of how the strategies differ on this corpus.
        """
        docs = load_documents(path)
        if not docs:
            raise ValueError(f"No indexable documents found at: {path}")

        stats: list[StrategyStats] = []
        for strategy, chunker in CHUNKERS.items():
            chunks: list[Chunk] = []
            for doc in docs:
                chunks.extend(chunker(doc, size=size, overlap=overlap))
            sizes = [c.metadata["n_chars"] for c in chunks] or [0]
            entry = StrategyStats(
                strategy=strategy,
                n_chunks=len(chunks),
                avg_chars=round(sum(sizes) / len(sizes)),
                min_chars=min(sizes),
                max_chars=max(sizes),
            )
            if query and chunks:
                vectors = self._embedder.embed_batch([c.text for c in chunks])
                records = [
                    {"text": c.text, "embedding": normalize(v), "metadata": c.metadata}
                    for c, v in zip(chunks, vectors)
                ]
                qv = self._embedder.embed_one(query)
                for hit in cosine_top_k(records, qv, k):
                    md = hit["metadata"]
                    entry.top_hits.append(
                        (hit["score"], md["filename"], md["section"])
                    )
            stats.append(entry)
        return stats
