"""Tests for JSON index storage and cosine search (jarvis.indexing.store)."""

import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.indexing.store import IndexStore, normalize, cosine_top_k


def _rec(chunk_id: str, embedding: list[float], text: str = "t", **md) -> dict:
    meta = {"chunk_id": chunk_id, "source": "s", "filename": "f.md",
            "title": "T", "section": "S"}
    meta.update(md)
    return {"chunk_id": chunk_id, "text": text, "embedding": embedding, "metadata": meta}


class NormalizeTest(unittest.TestCase):
    def test_unit_length(self):
        v = normalize([3.0, 4.0])
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in v)), 1.0)

    def test_zero_vector_unchanged(self):
        self.assertEqual(normalize([0.0, 0.0]), [0.0, 0.0])


class CosineTest(unittest.TestCase):
    def test_ranks_by_similarity(self):
        records = [
            _rec("a", [1.0, 0.0]),
            _rec("b", [0.0, 1.0]),
            _rec("c", [0.9, 0.1]),
        ]
        top = cosine_top_k(records, [1.0, 0.0], k=2)
        self.assertEqual(top[0]["metadata"]["chunk_id"], "a")
        self.assertEqual(top[1]["metadata"]["chunk_id"], "c")
        self.assertEqual(len(top), 2)


class StoreRoundTripTest(unittest.TestCase):
    def test_save_load_normalizes_and_preserves_metadata(self):
        with TemporaryDirectory() as tmp:
            store = IndexStore(Path(tmp))
            header = {"provider": "fake", "model": "m", "dim": 2, "strategy": "fixed"}
            store.save("kb", header, [_rec("a", [3.0, 4.0], section="Intro")])
            loaded = store.load("kb")
            self.assertIsNotNone(loaded)
            h, records = loaded
            self.assertEqual(h["provider"], "fake")
            self.assertIn("created_at", h)
            # Stored embedding is unit-normalized.
            norm = math.sqrt(sum(x * x for x in records[0]["embedding"]))
            self.assertAlmostEqual(norm, 1.0)
            self.assertEqual(records[0]["metadata"]["section"], "Intro")

    def test_list_and_delete(self):
        with TemporaryDirectory() as tmp:
            store = IndexStore(Path(tmp))
            store.save("one", {"dim": 1, "strategy": "fixed", "n_chunks": 1},
                       [_rec("a", [1.0])])
            self.assertEqual([h["name"] for h in store.list_all()], ["one"])
            self.assertTrue(store.delete("one"))
            self.assertFalse(store.delete("one"))
            self.assertEqual(store.list_all(), [])

    def test_search_returns_scored_records(self):
        with TemporaryDirectory() as tmp:
            store = IndexStore(Path(tmp))
            store.save("kb", {"dim": 2},
                       [_rec("a", [1.0, 0.0]), _rec("b", [0.0, 1.0])])
            results = store.search("kb", [1.0, 0.0], k=1)
            self.assertEqual(results[0]["metadata"]["chunk_id"], "a")
            self.assertIn("score", results[0])

    def test_search_rejects_dim_mismatch(self):
        with TemporaryDirectory() as tmp:
            store = IndexStore(Path(tmp))
            store.save("kb", {"dim": 2, "provider": "p", "model": "m"},
                       [_rec("a", [1.0, 0.0])])
            with self.assertRaises(ValueError):
                store.search("kb", [1.0, 0.0, 0.0])

    def test_search_missing_index_raises(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(KeyError):
                IndexStore(Path(tmp)).search("nope", [1.0])


if __name__ == "__main__":
    unittest.main()
