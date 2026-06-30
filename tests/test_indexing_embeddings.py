"""Tests for embedding providers and the factory (jarvis.indexing.embeddings)."""

import os
import unittest
from unittest import mock

from jarvis.indexing.embeddings import (
    FakeEmbedder,
    OllamaEmbedder,
    OpenRouterEmbedder,
    make_embedder,
)


class FakeEmbedderTest(unittest.TestCase):
    def test_deterministic_and_fixed_dim(self):
        e = FakeEmbedder(dim=32)
        self.assertEqual(e.embed_one("hello world"), e.embed_one("hello world"))
        self.assertEqual(len(e.embed_one("anything")), 32)

    def test_shared_words_are_more_similar(self):
        e = FakeEmbedder(dim=128)
        from jarvis.indexing.store import normalize, _dot
        a = normalize(e.embed_one("vector search embeddings"))
        b = normalize(e.embed_one("vector search index"))
        c = normalize(e.embed_one("completely different topic"))
        self.assertGreater(_dot(a, b), _dot(a, c))

    def test_batch_matches_one(self):
        e = FakeEmbedder()
        self.assertEqual(e.embed_batch(["x", "y"]), [e.embed_one("x"), e.embed_one("y")])


class FactoryTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("JARVIS_EMBED_PROVIDER", "JARVIS_EMBED_MODEL")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_default_is_ollama(self):
        e = make_embedder()
        self.assertIsInstance(e, OllamaEmbedder)
        self.assertEqual(e.model, "nomic-embed-text")

    def test_env_selects_provider_and_model(self):
        os.environ["JARVIS_EMBED_PROVIDER"] = "fake"
        os.environ["JARVIS_EMBED_MODEL"] = "custom"
        e = make_embedder()
        self.assertIsInstance(e, FakeEmbedder)
        self.assertEqual(e.model, "custom")

    def test_explicit_args_win(self):
        self.assertIsInstance(make_embedder("fake"), FakeEmbedder)

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            make_embedder("nope")


class OllamaHTTPTest(unittest.TestCase):
    def test_posts_prompt_and_parses_embedding(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        with mock.patch("jarvis.indexing.embeddings.requests.post",
                        return_value=resp) as post:
            vec = OllamaEmbedder(url="http://h:1").embed_one("hi")
        self.assertEqual(vec, [0.1, 0.2, 0.3])
        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith("/api/embeddings"))
        self.assertEqual(kwargs["json"]["prompt"], "hi")

    def test_raises_with_hint_on_failure(self):
        resp = mock.Mock(status_code=500, text="boom")
        with mock.patch("jarvis.indexing.embeddings.requests.post", return_value=resp):
            with self.assertRaises(RuntimeError) as ctx:
                OllamaEmbedder(max_retries=0).embed_one("hi")
        self.assertIn("ollama", str(ctx.exception).lower())


class OpenRouterHTTPTest(unittest.TestCase):
    def test_batches_and_orders_by_index(self):
        resp = mock.Mock(status_code=200)
        # Return out of order to verify re-sorting by 'index'.
        resp.json.return_value = {"data": [
            {"index": 1, "embedding": [2.0]},
            {"index": 0, "embedding": [1.0]},
        ]}
        with mock.patch("jarvis.indexing.embeddings.requests.post",
                        return_value=resp):
            vecs = OpenRouterEmbedder(api_key="k").embed_batch(["a", "b"])
        self.assertEqual(vecs, [[1.0], [2.0]])

    def test_missing_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with self.assertRaises(EnvironmentError):
                OpenRouterEmbedder()


if __name__ == "__main__":
    unittest.main()
