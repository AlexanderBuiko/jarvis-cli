"""Tests for engine selection and per-role routing (jarvis.llm.router)."""

import os
import unittest
from unittest import mock

from jarvis.config.manager import ConfigManager
from jarvis.llm.router import (
    EngineRouter,
    RoutingEngine,
    current_provider,
    make_engine,
)
from tests.fake_engine import FakeEngine


class MakeEngineTest(unittest.TestCase):
    def test_ollama_needs_no_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            from jarvis.ollama.client import OllamaClient
            self.assertIsInstance(make_engine("ollama"), OllamaClient)

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            make_engine("gigachat")

    def test_env_default(self):
        with mock.patch.dict(os.environ, {"JARVIS_LLM_PROVIDER": "ollama"}):
            from jarvis.ollama.client import OllamaClient
            self.assertIsInstance(make_engine(), OllamaClient)


class CurrentProviderTest(unittest.TestCase):
    def test_runtime_beats_env(self):
        cfg = ConfigManager()
        cfg.set("provider", "ollama")
        with mock.patch.dict(os.environ, {"JARVIS_LLM_PROVIDER": "openrouter"}):
            self.assertEqual(current_provider(cfg), "ollama")

    def test_default_is_openrouter(self):
        cfg = ConfigManager()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_LLM_PROVIDER", None)
            self.assertEqual(current_provider(cfg), "openrouter")


class _StubRouter:
    """Minimal router exposing .engine(provider) for RoutingEngine."""
    def __init__(self, engines):
        self._engines = engines
        self.asked = []

    def engine(self, provider):
        self.asked.append(provider)
        return self._engines[provider]


class RoutingEngineTest(unittest.TestCase):
    def test_delegates_to_current_provider_live(self):
        cloud = FakeEngine(scripted=["cloud"])
        local = FakeEngine(scripted=["local"])
        router = _StubRouter({"openrouter": cloud, "ollama": local})
        cfg = ConfigManager()
        eng = RoutingEngine(cfg, router)

        # Default → cloud.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_LLM_PROVIDER", None)
            self.assertEqual(eng.complete([], {}).text, "cloud")
            # Live toggle → local, no rebuild.
            cfg.set("provider", "ollama")
            self.assertEqual(eng.complete([], {}).text, "local")
        self.assertEqual(router.asked, ["openrouter", "ollama"])

    def test_pricing_delegates(self):
        local = FakeEngine()
        router = _StubRouter({"ollama": local})
        cfg = ConfigManager()
        cfg.set("provider", "ollama")
        self.assertEqual(RoutingEngine(cfg, router).get_pricing("x"), (None, None))


class EngineRouterTest(unittest.TestCase):
    def setUp(self):
        # Make engine construction hermetic — no real clients / API keys.
        self._engines = {"openrouter": FakeEngine(), "ollama": FakeEngine()}
        patcher = mock.patch(
            "jarvis.llm.router.make_engine", side_effect=lambda p: self._engines[p]
        )
        self.make_engine = patcher.start()
        self.addCleanup(patcher.stop)

    def test_engine_built_lazily_and_cached(self):
        router = EngineRouter(ConfigManager())
        self.assertEqual(self.make_engine.call_count, 0)
        e1 = router.engine("ollama")
        e2 = router.engine("ollama")
        self.assertIs(e1, e2)
        self.assertEqual(self.make_engine.call_count, 1)

    def test_role_unset_follows_main_gateway(self):
        router = EngineRouter(ConfigManager())
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_UTILITY_PROVIDER", None)
            self.assertIs(router.role_gateway("JARVIS_UTILITY_PROVIDER"), router.main_gateway)

    def test_role_pinned_to_provider(self):
        router = EngineRouter(ConfigManager())
        with mock.patch.dict(os.environ, {"JARVIS_UTILITY_PROVIDER": "ollama"}):
            gw = router.role_gateway("JARVIS_UTILITY_PROVIDER")
        self.assertIsNot(gw, router.main_gateway)
        # Pinned gateway wraps the ollama engine specifically.
        self.assertIs(gw._engine, self._engines["ollama"])

    def test_main_gateway_is_singleton(self):
        router = EngineRouter(ConfigManager())
        self.assertIs(router.main_gateway, router.main_gateway)


if __name__ == "__main__":
    unittest.main()
