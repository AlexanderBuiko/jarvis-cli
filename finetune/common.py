"""Shared constants and the review→training transform.

Defined once so every step — extract, convert, validate, split, baseline —
agrees on the exact label set and the exact system prompt. The lecture's rule
is that an identical format in every example is what the model locks onto, so
the single source of truth lives here rather than being retyped per script.
"""

from __future__ import annotations

import re

# ── Label vocabulary ─────────────────────────────────────────────────────────

# Order is priority, most-urgent first; used for reporting and tie-breaks.
LABELS: tuple[str, ...] = ("urgent_now", "today", "this_week", "ignore")

SYSTEM_PROMPT = (
    "You are a message-priority classifier. Read the incoming message and reply "
    "with exactly one label and nothing else: urgent_now, today, this_week, or ignore."
)


# ── Sanitisation ─────────────────────────────────────────────────────────────

# Applied to real inbox text before it becomes training data. Two goals at once:
# strip per-recipient secrets (email addresses, unsubscribe/OTP tokens, tracking
# URLs) so the dataset is safe to share, and drop leaked CSS/HTML/markup noise so
# the model learns from the message, not the payload. Order matters: kill CSS
# blocks and URLs before collapsing whitespace.
_CSS_BLOCK = re.compile(r"[.#@]?[\w\-\[\], >:]*\{[^{}]*\}")
_CSS_AT = re.compile(r"@[\w-]+[^{;]*[{;]")
_CSS_DECL = re.compile(r"[\w-]+\s*:\s*[^;\n]+!?\s*(?:important)?\s*;")
_URL = re.compile(r"https?://\S+|www\.\S+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")
_TOKEN = re.compile(r"(?<![\w])[A-Za-z0-9_%\-]{24,}(?![\w])")  # opaque tracking blobs
_ZWJ = re.compile(r"[​-‏⁠﻿]")
_WS = re.compile(r"[ \t]+")
_BLANK = re.compile(r"\n\s*\n\s*\n+")
_SANITISED_MAX = 600  # a priority label needs the lead, not the whole footer


def sanitize(text: str) -> str:
    """Strip secrets and markup noise from a raw inbox message.

    Redacts email addresses to ``[email]``, removes tracking URLs, opaque
    per-recipient tokens, HTML entities and leaked CSS, then collapses whitespace
    and truncates. Heuristic by design — it favours a clean, shareable lead over
    perfect fidelity, which is exactly what a classification example needs.
    """
    text = _CSS_BLOCK.sub(" ", text)
    text = _CSS_AT.sub(" ", text)
    text = _CSS_DECL.sub(" ", text)
    text = _URL.sub(" ", text)
    text = _EMAIL.sub("[email]", text)
    text = _ENTITY.sub(" ", text)
    text = _TOKEN.sub(" ", text)
    text = _ZWJ.sub("", text)
    text = _WS.sub(" ", text.replace("\r\n", "\n"))
    text = _BLANK.sub("\n\n", text).strip()
    if len(text) > _SANITISED_MAX:
        text = text[:_SANITISED_MAX].rsplit(" ", 1)[0].rstrip() + " […]"
    return text


# ── Transform ────────────────────────────────────────────────────────────────

def build_user_content(topic: str, author: str, message: str) -> str:
    """Render one message into the fixed user-turn layout shared by all examples."""
    return f"Topic: {topic}\nFrom: {author}\n\n{message}".strip()


def training_object(topic: str, author: str, message: str, label: str) -> dict:
    """A single JSONL training row: system + user + assistant, assistant = label.

    Kept as a plain ``dict`` on purpose — it is written straight to JSONL and
    read back by the OpenAI API, so a dataclass would only add a serialisation
    layer the rest of this tooling does not have.
    """
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_content(topic, author, message)},
            {"role": "assistant", "content": label},
        ]
    }
