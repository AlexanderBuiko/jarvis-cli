import unittest

from jarvis.config.manager import ConfigManager


class PresencePenaltyConfigParameter(unittest.TestCase):
    def test_a_value_within_range_is_accepted_and_parsed_as_float(self):
        cfg = ConfigManager()
        cfg.set("presence_penalty", "0.5")
        self.assertEqual(cfg.runtime["presence_penalty"], 0.5)

    def test_a_value_outside_the_minus_two_to_two_range_is_rejected(self):
        cfg = ConfigManager()
        with self.assertRaises(ValueError):
            cfg.set("presence_penalty", "3.0")


if __name__ == "__main__":
    unittest.main()
