"""
Local JSON index storage.

One index per file under ``~/.jarvis/indexes/<name>.json``:

    {
      "header":  { name, provider, model, dim, strategy, size, overlap,
                   n_documents, n_chunks, sources, created_at },
      "records": [ { chunk_id, text, embedding, metadata }, … ]
    }

JSON is chosen to match the project (threads/tasks/profile are all inspectable
JSON, zero extra dependencies) and the lecture's small-scale testing scope. Each
embedding is **unit-normalized at write time** (the lecture's normalization step),
so cosine similarity is a plain dot product at query time. A FAISS / sqlite-vec
backend would slot in behind this same class if the corpus ever outgrew an
in-memory linear scan.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

# Env var overriding where indexes are read/written. Kept here (not in a call site)
# so every ``IndexStore()`` — CLI build, REPL, and the remote server that reuses this
# class — resolves the same directory. This is the "config not code" seam: point it
# at a mounted GCS bucket on Cloud Run and nothing else changes.
INDEX_DIR_ENV = "JARVIS_INDEX_DIR"


def default_index_dir() -> Path:
    """Resolve the index directory from ``JARVIS_INDEX_DIR``, else ``~/.jarvis/indexes``.

    Read at call time (not import) so it reflects env/.env loaded at startup and stays
    test-isolatable via ``$HOME`` / the env var.
    """
    override = os.environ.get(INDEX_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".jarvis" / "indexes"


def normalize(vec: list[float]) -> list[float]:
    """Return the unit-length version of ``vec`` (unchanged if it is all zeros)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [x / norm for x in vec]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def cosine_top_k(
    records: list[dict],
    query_vector: list[float],
    k: int = 5,
) -> list[dict]:
    """Rank ``records`` by cosine similarity to ``query_vector``; return top-k.

    Record embeddings are assumed already normalized (as stored); the query
    vector is normalized here. Each result is ``{score, text, metadata}``.
    """
    qv = normalize(query_vector)
    scored = [
        {
            "score": _dot(qv, rec["embedding"]),
            "text": rec["text"],
            "metadata": rec["metadata"],
        }
        for rec in records
    ]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[: max(0, k)]


class IndexStore:
    def __init__(self, directory: Path | None = None) -> None:
        # Resolve at instantiation (not import) so $HOME/env-based isolation works.
        # Default honours JARVIS_INDEX_DIR (see default_index_dir).
        self._dir = directory or default_index_dir()

    # ── Write ────────────────────────────────────────────────────────────────

    def save(self, name: str, header: dict, records: list[dict]) -> Path:
        """Persist an index. Embeddings are normalized before writing."""
        self._dir.mkdir(parents=True, exist_ok=True)
        stored = [
            {
                "chunk_id": rec["chunk_id"],
                "text": rec["text"],
                "embedding": normalize(rec["embedding"]),
                "metadata": rec["metadata"],
            }
            for rec in records
        ]
        full_header = {**header, "name": name, "created_at": _now()}
        path = self._path(name)
        path.write_text(
            json.dumps({"header": full_header, "records": stored},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if path.exists():
            path.unlink()
            return True
        return False

    # ── Read ─────────────────────────────────────────────────────────────────

    def load(self, name: str) -> tuple[dict, list[dict]] | None:
        """Return (header, records) for an index, or None if it doesn't exist."""
        path = self._path(name)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("header") or {}, data.get("records") or []

    def load_header(self, name: str) -> dict | None:
        loaded = self.load(name)
        return loaded[0] if loaded else None

    def list_all(self) -> list[dict]:
        """Index headers, newest first (by file mtime)."""
        if not self._dir.exists():
            return []
        results = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            header = data.get("header") or {}
            header.setdefault("name", path.stem)
            header["_mtime"] = path.stat().st_mtime
            results.append(header)
        results.sort(key=lambda h: h.get("_mtime", 0), reverse=True)
        return results

    def search(self, name: str, query_vector: list[float], k: int = 5) -> list[dict]:
        """Cosine top-k over a stored index.

        Raises ``KeyError`` if the index is missing and ``ValueError`` if the
        query vector's dimension doesn't match what the index was built with
        (i.e. a different embedding model) — the follow-up RAG path relies on this
        guard so a question is never searched against an incompatible index.
        """
        loaded = self.load(name)
        if loaded is None:
            raise KeyError(f"No such index: '{name}'")
        header, records = loaded
        dim = header.get("dim")
        if dim and len(query_vector) != dim:
            raise ValueError(
                f"Query vector dim {len(query_vector)} != index dim {dim} "
                f"(index '{name}' was built with {header.get('provider')}/"
                f"{header.get('model')}). Embed the query with the same model."
            )
        return cosine_top_k(records, query_vector, k)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

def _demo_divide(x):
    return x / 0  # demo: intentional bug for the AI reviewer
