"""Tier 1 — the embedding nearest-centroid micro-classifier.

The micro-model is deliberately *not* an LLM. It embeds the labelled training
messages once, averages each class into a centroid, and classifies a new message
by cosine similarity to those centroids. No text generation — one embedding call
plus a handful of dot products.

Its confidence has two parts, because two different things make a prediction
untrustworthy:

* **top similarity** — how close the message is to its nearest class at all. A
  garbled or off-topic message is far from *every* centroid; low top-similarity is
  the out-of-distribution signal.
* **margin** — how far ahead the nearest class is over the runner-up. A message
  that sits between two classes has a small margin; that is the borderline signal.

``OK`` requires both to clear their floors; otherwise ``UNSURE``, which is what
sends the message to the big model. So the micro-model rejects for the right two
reasons instead of one blunt score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from jarvis.indexing.embeddings import Embedder


@dataclass
class MicroResult:
    label: str            # best-guess class (argmax cosine), even when UNSURE
    status: str           # OK | UNSURE
    top_sim: float        # cosine to the nearest centroid (out-of-distribution signal)
    margin: float         # nearest minus runner-up cosine (borderline signal)
    scores: dict[str, float]  # per-label cosine, for the report


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class MicroClassifier:
    """A cosine nearest-centroid classifier over embeddings — fit once, classify cheaply."""

    def __init__(self, embedder: Embedder, sim_floor: float = 0.6, margin_floor: float = 0.02) -> None:
        self.embedder = embedder
        self.sim_floor = sim_floor      # below this top similarity → UNSURE (off-distribution)
        self.margin_floor = margin_floor  # below this lead over runner-up → UNSURE (borderline)
        self._centroids: dict[str, list[float]] = {}

    def fit(self, examples: list[tuple[str, str]]) -> "MicroClassifier":
        """Build one L2-normalized centroid per label from ``(text, label)`` pairs."""
        by_label: dict[str, list[list[float]]] = {}
        texts = [t for t, _ in examples]
        vectors = self.embedder.embed_batch(texts)
        for (_, label), vec in zip(examples, vectors):
            by_label.setdefault(label, []).append(_normalize(vec))
        for label, vecs in by_label.items():
            mean = [sum(col) / len(vecs) for col in zip(*vecs)]
            self._centroids[label] = _normalize(mean)
        return self

    def classify(self, text: str) -> MicroResult:
        """Embed the text and score it against every class centroid."""
        query = _normalize(self.embedder.embed_one(text))
        scores = {label: _dot(query, centroid) for label, centroid in self._centroids.items()}
        ranked = sorted(scores.values(), reverse=True)
        top_sim = ranked[0]
        margin = top_sim - (ranked[1] if len(ranked) > 1 else -1.0)
        label = max(scores, key=scores.get)
        status = "OK" if (top_sim >= self.sim_floor and margin >= self.margin_floor) else "UNSURE"
        return MicroResult(label=label, status=status, top_sim=round(top_sim, 4),
                           margin=round(margin, 4), scores={k: round(v, 4) for k, v in scores.items()})
