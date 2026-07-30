"""The two length-based uncertainty signals, as pure functions.

Kept separate from the routing policy so each signal is trivially testable and the
policy in ``router.py`` reads as a rule over named signals. The confidence signal
needs no function — it is the number the model returns; these cover the second
heuristic the brief names, "response length", plus explicit hedging.
"""

from __future__ import annotations

import re

# Strong, unambiguous uncertainty markers only. Deliberately excludes soft words
# like "might"/"possibly" that appear in perfectly good nuanced answers — those
# would fire on correct replies and inflate escalation.
_HEDGE = re.compile(
    r"\b(not sure|not certain|cannot be certain|can'?t be certain|i don'?t know|"
    r"i do not know|no idea|it depends|hard to say|unclear|i'?m unsure|i'?m guessing)\b",
    re.IGNORECASE,
)


def word_count(text: str) -> int:
    """Words in the answer — the 'response length' heuristic's raw measure."""
    return len(text.split())


def is_hedged(text: str) -> bool:
    """True when the answer text explicitly admits uncertainty."""
    return bool(_HEDGE.search(text))
