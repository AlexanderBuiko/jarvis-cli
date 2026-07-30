"""The query series the router is tested on.

Two intended buckets. ``expected`` is the tier a human would guess handles each
query — it is a *sanity check* for the report ("did routing agree with
intuition?"), not a hard label the router is graded against. What the assignment
actually asks for is the split the router produces: which queries stayed on the
small model, which went to the big one.

* **easy** — simple facts and one-step questions a small model should answer
  confidently → expected to stay on the cheap tier.
* **hard** — multi-step reasoning, deliberately ambiguous, niche, or open-ended
  questions where a small model should be unsure → expected to escalate.

All authored here; no personal data, so the set is committed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Query:
    name: str       # short id for the report
    bucket: str     # easy | hard
    expected: str   # cheap | strong — the intuitive tier, for the sanity column
    text: str       # the exact user turn sent to the model


_EASY = [
    Query("capital-france", "easy", "cheap", "What is the capital of France?"),
    Query("arithmetic", "easy", "cheap", "What is 17 + 25?"),
    Query("week-days", "easy", "cheap", "How many days are in a week?"),
    Query("json-define", "easy", "cheap", "In one sentence, what is JSON?"),
    Query("water-boil", "easy", "cheap", "At what temperature does water boil at sea level, in Celsius?"),
    Query("greeting", "easy", "cheap", "Say hello in one short, friendly sentence."),
]

_HARD = [
    Query("bat-and-ball", "hard", "strong",
          "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. "
          "How much does the ball cost?"),
    Query("word-problem", "hard", "strong",
          "A train leaves at 2:15 pm and arrives at 5:00 pm. It stopped for 20 minutes on the way. "
          "How long was it actually moving?"),
    Query("ambiguous", "hard", "strong",
          "Is it better?"),
    Query("niche-fact", "hard", "strong",
          "What was the exact attendance figure at the 1936 Berlin Olympics opening ceremony?"),
    Query("tradeoffs", "hard", "strong",
          "What are the main trade-offs between a microservices architecture and a monolith, "
          "and when would you prefer each?"),
    Query("code-edgecase", "hard", "strong",
          "Write a Python function that returns the median of a list of numbers and correctly "
          "handles both an empty list and an even-length list."),
]


def all_queries() -> list[Query]:
    return _EASY + _HARD
