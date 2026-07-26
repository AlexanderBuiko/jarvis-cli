import unittest

from jarvis.config.manager import ConfigManager
from jarvis.repl.commands import handle_models


class ModelsCommandListsProvidersWithActiveDefault(unittest.TestCase):
    def test_active_provider_is_starred_and_the_other_is_not(self):
        cfg = ConfigManager()
        cfg.set("provider", "ollama")

        lines = handle_models(cfg).splitlines()
        ollama_line = next(line for line in lines if "ollama" in line)
        openrouter_line = next(line for line in lines if "openrouter" in line)

        self.assertIn("*", ollama_line)
        self.assertNotIn("*", openrouter_line)

    def test_config_set_model_overrides_the_active_provider_id(self):
        cfg = ConfigManager()
        cfg.set("provider", "openrouter")
        cfg.set("model", "anthropic/claude-3.5-sonnet")

        self.assertIn("anthropic/claude-3.5-sonnet", handle_models(cfg))


if __name__ == "__main__":
    unittest.main()
