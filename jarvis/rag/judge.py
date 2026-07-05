"""
LLM-as-judge for the "does the answer's meaning match its quotes" check.

Given a grounded answer and the verbatim quotes it cited, ask the model whether
the answer's claims are actually supported by those quotes (not by outside
knowledge). This replaces the earlier lexical-overlap proxy — it judges meaning,
not word overlap, so a faithful paraphrase counts as supported.

Costs one model call per judged answer; used only by the eval when answers are
generated. Runs through the same gateway as everything else.
"""

from __future__ import annotations

import re
from typing import Any

_JUDGE_SYSTEM = (
    "You are an evaluator for a retrieval-augmented answer. You are given an ANSWER "
    "and the SOURCE quotes it was based on. Decide whether the answer's main claims "
    "are supported by the sources — judge meaning, not exact wording, and allow "
    "reasonable paraphrase and synthesis across the sources. An answer counts as "
    "supported if its key claims are backed by the sources, even if it words them "
    "differently or adds small connective phrasing. Reply with exactly one word: "
    "YES if supported, or NO if it makes a claim the sources contradict or don't "
    "cover at all."
)

_YES = re.compile(r"\bYES\b")
_NO = re.compile(r"\bNO\b")


def judge_supported(
    gateway: Any, answer: str, quotes: str, *, model: str | None = None
) -> bool:
    """True if the model judges ``answer`` supported by ``quotes`` (the cited source
    text). Empty answer or source → False. Any error is swallowed to False so a
    judge hiccup never breaks an eval run."""
    if not answer.strip() or not quotes.strip():
        return False
    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": f"SOURCES:\n{quotes}\n\nANSWER:\n{answer}\n\n"
                                     "Is the answer supported by the sources? Reply YES or NO."},
    ]
    params = {"model": model} if model else {}
    try:
        verdict = gateway.complete(messages, params, label="rag_judge").text.upper()
    except Exception:  # noqa: BLE001 — a judge failure must not abort the eval
        return False
    # Whichever of YES / NO appears first as a word wins (robust to a model that
    # explains before answering). No YES at all → not supported.
    y, n = _YES.search(verdict), _NO.search(verdict)
    if not y:
        return False
    return not n or y.start() < n.start()
