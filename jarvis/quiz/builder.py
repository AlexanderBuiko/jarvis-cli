"""
MCQ generation from a local index.

For each sampled chunk the local model writes ONE multiple-choice question that
tests understanding of the concept — grounded in the chunk but **not quoting it**.
Every generated item is validated:

  • strict shape — a non-empty stem, exactly 4 distinct non-empty options, and a
    ``correct_index`` in range;
  • a **leakage guard** — the stem and options must not copy a long verbatim span
    from the source chunk, and must not name a source file. This keeps the pool
    transformative (concept tests, not excerpts), which is what makes it safe to
    hand to the bot server.

Items that fail validation are regenerated once, then dropped. Topics are mapped to
generic labels (coroutines / compose / kotlin) so the pool carries no source
identity.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

# complete(messages, params) -> assistant text. Injected so tests need no network.
CompleteFn = Callable[[list[dict], dict], str]

# Filename → generic topic. Anything unmapped falls back to "android".
_TOPIC_MAP = {
    "kotlin-coroutines": "coroutines",
    "coroutines": "coroutines",
    "compose-internals": "compose",
    "compose": "compose",
    "effective-kotlin": "kotlin",
    "kotlin": "kotlin",
}

# A generated span this many consecutive source words long (or more) counts as
# copied text and fails the leakage guard.
_VERBATIM_MIN_WORDS = 8
# Chunks shorter than this have too little to test — skip them.
_MIN_CHUNK_CHARS = 250

_SYSTEM = (
    "You write multiple-choice questions to help an Android engineer prepare for "
    "technical interviews. Given a REFERENCE passage, write ONE question that tests "
    "understanding of a concept in it. Do NOT quote or copy the passage — phrase the "
    "question and options in your own words. Provide exactly four options: one clearly "
    "correct and three plausible but incorrect. Do not mention the reference, its "
    "source, a book, or a filename. Respond with ONLY a JSON object of the form: "
    '{"question": "...", "options": ["...","...","...","..."], "correct_index": 0}'
)


@dataclass
class MCQ:
    id: str
    topic: str
    question: str
    options: list[str]
    correct_index: int


def _topic_for(filename: str | None) -> str:
    stem = (filename or "").rsplit(".", 1)[0].lower()
    return _TOPIC_MAP.get(stem, "android")


def _norm_words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()


def _has_verbatim_span(text: str, source_words: list[str], min_words: int = _VERBATIM_MIN_WORDS) -> bool:
    """True if ``text`` shares a run of >= min_words consecutive words with the source."""
    words = _norm_words(text)
    if len(words) < min_words:
        return False
    source_ngrams = {
        " ".join(source_words[i:i + min_words])
        for i in range(len(source_words) - min_words + 1)
    }
    for i in range(len(words) - min_words + 1):
        if " ".join(words[i:i + min_words]) in source_ngrams:
            return True
    return False


def _parse_mcq(text: str) -> dict | None:
    """Extract the first JSON object from the model's reply, tolerating fences/prose."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _valid_shape(obj: dict) -> bool:
    q = obj.get("question")
    opts = obj.get("options")
    ci = obj.get("correct_index")
    if not isinstance(q, str) or not q.strip():
        return False
    if not isinstance(opts, list) or len(opts) != 4:
        return False
    if any(not isinstance(o, str) or not o.strip() for o in opts):
        return False
    if len({o.strip().lower() for o in opts}) != 4:  # options must be distinct
        return False
    return isinstance(ci, bool) is False and isinstance(ci, int) and 0 <= ci < 4


def _leaks(obj: dict, source_words: list[str]) -> bool:
    """True if the question or any option copies source text or names a file."""
    parts = [obj["question"], *obj["options"]]
    for p in parts:
        if ".md" in p.lower() or _has_verbatim_span(p, source_words):
            return True
    return False


def generate_mcq(
    complete: CompleteFn,
    chunk_text: str,
    topic: str,
    qid: str,
    params: dict | None = None,
) -> MCQ | None:
    """Generate and validate a single MCQ from a chunk; None if it can't be made cleanly."""
    source_words = _norm_words(chunk_text)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"REFERENCE:\n{chunk_text}\n\nWrite the question now as JSON."},
    ]
    reply = complete(messages, params or {})
    obj = _parse_mcq(reply)
    if not obj or not _valid_shape(obj) or _leaks(obj, source_words):
        return None
    return MCQ(
        id=qid,
        topic=topic,
        question=obj["question"].strip(),
        options=[o.strip() for o in obj["options"]],
        correct_index=int(obj["correct_index"]),
    )


def build_pool(
    records: list[dict],
    complete: CompleteFn,
    *,
    count: int = 40,
    params: dict | None = None,
    seed: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[MCQ]:
    """Sample chunks and generate up to ``count`` validated MCQs.

    Chunks too short to test are skipped. Each generation that fails validation is
    retried once, then dropped — so the returned pool may be slightly smaller than
    ``count``, but every item is clean.
    """
    usable = [r for r in records if len((r.get("text") or "")) >= _MIN_CHUNK_CHARS]
    rng = random.Random(seed)
    rng.shuffle(usable)

    pool: list[MCQ] = []
    seen_questions: set[str] = set()
    for rec in usable:
        if len(pool) >= count:
            break
        chunk = rec["text"]
        topic = _topic_for((rec.get("metadata") or {}).get("filename"))
        qid = f"q{len(pool) + 1}"
        mcq = generate_mcq(complete, chunk, topic, qid, params)
        if mcq is None:  # one retry
            mcq = generate_mcq(complete, chunk, topic, qid, params)
        if mcq is None:
            continue
        key = mcq.question.strip().lower()
        if key in seen_questions:  # avoid near-duplicate stems
            continue
        seen_questions.add(key)
        pool.append(mcq)
        if on_progress:
            on_progress(len(pool), count)
    return pool


def validate_pool(data: Any) -> list[str]:
    """Return a list of problems with a pool payload; empty means valid.

    Shared with the server's upload endpoint (imported there) so both ends agree on
    the schema.
    """
    errors: list[str] = []
    if not isinstance(data, list) or not data:
        return ["pool must be a non-empty list"]
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"item {i}: not an object")
            continue
        if not _valid_shape(item):
            errors.append(f"item {i}: bad shape (need question, 4 distinct options, correct_index 0-3)")
        for field in ("id", "topic"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"item {i}: missing '{field}'")
    return errors


def mcqs_to_json(pool: list[MCQ]) -> str:
    return json.dumps([asdict(m) for m in pool], ensure_ascii=False, indent=2)
