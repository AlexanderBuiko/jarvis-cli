"""
Second-stage retrieval enhancements: relevance filter, cross-encoder rerank,
and query rewrite.

First-stage search (embeddings + cosine) is fast but approximate. These add a
step *after* it so the LLM sees fewer, more relevant chunks:

- ``apply_filter``      — the free heuristic default: drop chunks below a cosine
                          cutoff, keep the top-N. Deterministic, no model.
- ``CrossEncoderReranker`` — an optional, more accurate reorder: a cross-encoder
                          scores each (question, chunk) pair jointly. Reuses a free
                          local sentence-transformers model; the dependency is
                          lazily imported so the base install stays lean.
- ``rewrite_query``     — reformulate the question into a better search query
                          before embedding (one LLM call, opt-in).

``enhance_results`` ties the post-search steps together: filter on the first-stage
cosine score, then optionally rerank the survivors, then keep top-N. Filtering
uses the cosine score (not the rerank score) so the cutoff means the same thing
whether or not reranking is on. It never returns empty when input was non-empty.
"""

from __future__ import annotations

from typing import Any, Protocol

DEFAULT_CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker(Protocol):
    def rerank(self, question: str, results: list[dict]) -> list[dict]:
        """Return ``results`` reordered by relevance to ``question`` (best first)."""
        ...


def apply_filter(
    results: list[dict],
    *,
    min_score: float | None = None,
    top_n: int | None = None,
) -> list[dict]:
    """Drop chunks below ``min_score`` (by cosine 'score'), then keep ``top_n``.

    Never empties a non-empty input: if the cutoff removes everything, the single
    best-scoring chunk is kept so the turn still has something to ground on.
    """
    kept = results
    if min_score is not None:
        kept = [r for r in results if r.get("score", 0.0) >= min_score]
        if not kept and results:
            kept = [max(results, key=lambda r: r.get("score", 0.0))]
    if top_n is not None:
        kept = kept[:top_n]
    return kept


def enhance_results(
    results: list[dict],
    *,
    min_score: float | None = None,
    top_n: int | None = None,
    reranker: Reranker | None = None,
    question: str | None = None,
) -> list[dict]:
    """Apply the full second stage: filter → optional rerank → top-N."""
    # 1) Relevance filter on the first-stage cosine score.
    kept = apply_filter(results, min_score=min_score)
    # 2) Optional cross-encoder rerank of the survivors.
    if reranker is not None and question is not None and kept:
        kept = reranker.rerank(question, kept)
    # 3) Keep the final top-N.
    if top_n is not None:
        kept = kept[:top_n]
    return kept


class CrossEncoderReranker:
    """Cross-encoder reranker backed by a local sentence-transformers model.

    Free to run (open-source model, CPU, no API), but needs the optional
    ``sentence-transformers`` package. The import and model load happen here so
    nothing is paid unless the reranker is actually constructed; the model is
    reused across calls by the caller (the agent caches instances by kind).
    """

    def __init__(self, model_name: str = DEFAULT_CROSS_ENCODER) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "rag_rerank=cross_encoder needs the optional 'sentence-transformers' "
                "package. Install it: pip install sentence-transformers"
            ) from exc
        self.model_name = model_name
        self._model = CrossEncoder(model_name)

    def rerank(self, question: str, results: list[dict]) -> list[dict]:
        pairs = [(question, r.get("text", "")) for r in results]
        scores = self._model.predict(pairs)
        ranked = sorted(zip(results, scores), key=lambda pair: pair[1], reverse=True)
        # Attach the cross-encoder score (for display) without mutating the input.
        return [{**r, "rerank_score": float(s)} for r, s in ranked]


def make_reranker(kind: str) -> Reranker | None:
    """Build a reranker by name. 'off' → None; 'cross_encoder' → CrossEncoderReranker."""
    if kind in ("off", None, ""):
        return None
    if kind == "cross_encoder":
        return CrossEncoderReranker()
    raise ValueError(f"Unknown rag_rerank '{kind}'. Use one of: off, cross_encoder.")


_REWRITE_SYSTEM = (
    "You rewrite a user's question into a single, concise search query for a "
    "vector database of documentation. Expand vague wording, keep the key nouns "
    "and technical terms, drop conversational filler. Reply with ONLY the query "
    "text — no quotes, no explanation."
)


def rewrite_query(gateway: Any, question: str, params: dict) -> str:
    """Reformulate ``question`` into a better search query via one LLM call.

    Falls back to the original question if the model returns nothing usable.
    Uses only the model setting from ``params`` (no sampling knobs) for a stable,
    cheap rewrite.
    """
    call_params = {"model": params["model"]} if params.get("model") else {}
    messages = [
        {"role": "system", "content": _REWRITE_SYSTEM},
        {"role": "user", "content": question},
    ]
    text = gateway.complete(messages, call_params, label="rag_rewrite").text.strip()
    text = text.strip("\"'").strip()
    return text or question
