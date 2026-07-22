"""Range validation for numeric config params driven by _PARAM_VALIDATORS.

Guards antipattern 5: a param that parses but has no validator is accepted
unchecked. These cover the three int params (max_tokens, top_k, seed) that were
parsing without a range check.
"""

import pytest

from jarvis.config.manager import ConfigManager


def test_negative_max_tokens_is_rejected():
    c = ConfigManager()
    with pytest.raises(ValueError, match="max_tokens must be a positive integer"):
        c.set("max_tokens", "-100")


def test_zero_max_tokens_is_rejected():
    c = ConfigManager()
    with pytest.raises(ValueError, match="max_tokens must be a positive integer"):
        c.set("max_tokens", "0")


def test_positive_max_tokens_is_accepted():
    c = ConfigManager()
    assert c.set("max_tokens", "512") == "max_tokens = 512"


def test_negative_top_k_is_rejected():
    c = ConfigManager()
    with pytest.raises(ValueError, match="top_k must be 0 or greater"):
        c.set("top_k", "-5")


def test_zero_top_k_is_accepted_as_disabled():
    c = ConfigManager()
    assert c.set("top_k", "0") == "top_k = 0"


def test_negative_seed_is_rejected():
    c = ConfigManager()
    with pytest.raises(ValueError, match="seed must be a non-negative integer"):
        c.set("seed", "-1")


def test_none_seed_is_accepted():
    c = ConfigManager()
    assert c.set("seed", "none") == "seed = None"
