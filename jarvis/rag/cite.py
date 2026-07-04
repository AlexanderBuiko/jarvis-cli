"""
Mandatory citations and the weak-context "I don't know" gate.

After a grounded answer is generated, ``build_citations`` appends a guaranteed,
verbatim block:

    Sources:
      - filename › section  (chunk_id)
    Quotes:
      [1] filename › section: "…verbatim fragment from the chunk…"

The model is asked to mark the excerpts it used by ``[n]`` (see build_rag_block);
if it did, only those chunks are cited, otherwise all found chunks are. Quotes are
sliced straight from the chunk text, so they can't be paraphrased or invented.

``idk_message`` is the deterministic weak-context response used by strict mode.
"""

from __future__ import annotations

import re

_CITE_RE = re.compile(r"\[(\d+)\]")
_MAX_QUOTE_CHARS = 220
_STOPWORDS = frozenset(
    "the a an of to in on for and or is are how do i you it with as at be this that "
    "your can when what which from by".split()
)


def cited_indices(answer_text: str, n: int) -> list[int]:
    """1-based excerpt numbers the answer referenced via [n], within range."""
    seen: list[int] = []
    for m in _CITE_RE.findall(answer_text or ""):
        i = int(m)
        if 1 <= i <= n and i not in seen:
            seen.append(i)
    return seen


def pick_quote(text: str, question: str) -> str:
    """A short **verbatim** fragment of ``text`` — the sentence overlapping the
    question most, else the leading fragment. Always a substring of ``text``."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    if not sentences:
        return _clip(text.strip())
    q_words = _words(question)
    best, best_score = sentences[0], -1
    for s in sentences:
        score = len(_words(s) & q_words)
        if score > best_score:
            best, best_score = s, score
    return _clip(best)


def build_citations(results: list[dict], answer_text: str, question: str) -> str:
    """The verbatim Sources + Quotes appendix for the chunks the answer used."""
    if not results:
        return ""
    picked = cited_indices(answer_text, len(results))
    used = [results[i - 1] for i in picked] if picked else results

    source_lines, quote_lines, seen = [], [], set()
    for n, r in enumerate(used, 1):
        md = r.get("metadata", {})
        cite = f"{md.get('filename', '?')} › {md.get('section', '')}".rstrip(" ›")
        cid = md.get("chunk_id", "?")
        key = cid
        if key not in seen:
            seen.add(key)
            source_lines.append(f"  - {cite}  ({cid})")
        quote = pick_quote(r.get("text", ""), question)
        quote_lines.append(f'  [{n}] {cite}: "{quote}"')

    return "Sources:\n" + "\n".join(source_lines) + "\n\nQuotes:\n" + "\n".join(quote_lines)


def idk_message(question: str, best_score: float, threshold: float) -> str:
    """Deterministic weak-context reply for strict mode: decline + ask to clarify."""
    return (
        "I don't know — I couldn't find confidently relevant information in the "
        f"knowledge base for this (best match scored {best_score:.2f}, below the "
        f"{threshold:.2f} relevance bar). Could you clarify or rephrase? For "
        "example, add more specific terms, or tell me which topic or document you "
        "mean."
    )


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z_]+", (text or "").lower())
            if len(w) > 2 and w not in _STOPWORDS}


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_QUOTE_CHARS else text[:_MAX_QUOTE_CHARS - 1].rstrip() + "…"
