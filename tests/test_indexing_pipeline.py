"""End-to-end pipeline tests with the offline FakeEmbedder (jarvis.indexing.pipeline)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.indexing.embeddings import FakeEmbedder
from jarvis.indexing.pipeline import IndexPipeline
from jarvis.indexing.store import IndexStore

DOC_A = """# Vector Search

## Embeddings

Embeddings turn text into vectors so cosine similarity can rank meaning.

## Chunking

Split documents into overlapping chunks before embedding them.
"""

DOC_B = """# Cooking

## Pasta

Boil water, add salt, cook the pasta until al dente, then drain.
"""


def _corpus(tmp: str) -> str:
    root = Path(tmp) / "kb"
    root.mkdir()
    (root / "search.md").write_text(DOC_A, encoding="utf-8")
    (root / "cooking.md").write_text(DOC_B, encoding="utf-8")
    return str(root)


class BuildSearchTest(unittest.TestCase):
    def test_build_then_load_round_trip(self):
        with TemporaryDirectory() as tmp:
            store = IndexStore(Path(tmp) / "idx")
            pipe = IndexPipeline(FakeEmbedder(), store)
            res = pipe.build(_corpus(tmp), "kb", strategy="structure")
            self.assertEqual(res.n_documents, 2)
            self.assertGreater(res.n_chunks, 0)
            self.assertEqual(res.provider, "fake")

            loaded = store.load("kb")
            self.assertIsNotNone(loaded)
            header, records = loaded
            self.assertEqual(header["n_chunks"], res.n_chunks)
            self.assertEqual(len(records), res.n_chunks)
            # Every required metadata field is persisted with each chunk.
            for rec in records:
                self.assertTrue(
                    {"source", "filename", "title", "section", "chunk_id"}
                    .issubset(rec["metadata"])
                )

    def test_search_returns_relevant_chunk(self):
        with TemporaryDirectory() as tmp:
            pipe = IndexPipeline(FakeEmbedder(), IndexStore(Path(tmp) / "idx"))
            pipe.build(_corpus(tmp), "kb", strategy="structure")
            results = pipe.search("kb", "embeddings and cosine similarity", k=1)
            self.assertEqual(len(results), 1)
            # The vector-search doc, not the cooking doc, should win.
            self.assertEqual(results[0]["metadata"]["filename"], "search.md")
            self.assertIn("score", results[0])

    def test_build_unknown_strategy_raises(self):
        with TemporaryDirectory() as tmp:
            pipe = IndexPipeline(FakeEmbedder(), IndexStore(Path(tmp) / "idx"))
            with self.assertRaises(ValueError):
                pipe.build(_corpus(tmp), "kb", strategy="nope")

    def test_build_empty_dir_raises(self):
        with TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            pipe = IndexPipeline(FakeEmbedder(), IndexStore(Path(tmp) / "idx"))
            with self.assertRaises(ValueError):
                pipe.build(str(empty), "kb")


class CompareTest(unittest.TestCase):
    def test_compare_reports_both_strategies(self):
        with TemporaryDirectory() as tmp:
            pipe = IndexPipeline(FakeEmbedder(), IndexStore(Path(tmp) / "idx"))
            stats = pipe.compare(_corpus(tmp), size=200, overlap=20,
                                 query="how to chunk text")
            strategies = {s.strategy for s in stats}
            self.assertEqual(strategies, {"fixed", "structure"})
            for s in stats:
                self.assertGreater(s.n_chunks, 0)
                self.assertTrue(s.top_hits)  # query produced ranked hits

    def test_compare_without_query_skips_embedding(self):
        with TemporaryDirectory() as tmp:
            # A FakeEmbedder that would explode if embed_* were called, proving
            # compare() does no embedding when no query is given.
            class Boom(FakeEmbedder):
                def embed_batch(self, texts):  # noqa: D401
                    raise AssertionError("should not embed without a query")

                def embed_one(self, text):
                    raise AssertionError("should not embed without a query")

            pipe = IndexPipeline(Boom(), IndexStore(Path(tmp) / "idx"))
            stats = pipe.compare(_corpus(tmp))
            self.assertEqual({s.strategy for s in stats}, {"fixed", "structure"})


if __name__ == "__main__":
    unittest.main()
