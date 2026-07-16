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

# Inline citation bracket: one or more numbers, e.g. "[1]", "[3, 1]", "[1,2,3]".
_CITE_RE = re.compile(r"\[([\d,\s]+)\]")
# A standalone header line the model sometimes emits to start its own citation
# block (optionally wrapped in markdown **): "Sources:", "**References**", etc.
_MODEL_CITE_HEADER = re.compile(
    r"(?im)^\s*\*{0,2}(sources|references|citations|quotes)\*{0,2}\s*:?\s*$"
)
_MAX_QUOTE_CHARS = 220
_STOPWORDS = frozenset(
    "the a an of to in on for and or is are how do i you it with as at be this that "
    "your can when what which from by".split()
)


def cited_indices(answer_text: str, n: int) -> list[int]:
    """1-based excerpt numbers the answer referenced via [n], within range.

    Handles multi-number brackets like "[3, 1]" and "[1,2,3]", not just "[1]".
    """
    seen: list[int] = []
    for group in _CITE_RE.findall(answer_text or ""):
        for num in re.findall(r"\d+", group):
            i = int(num)
            if 1 <= i <= n and i not in seen:
                seen.append(i)
    return seen


def strip_trailing_citations(answer: str) -> str:
    """Remove a model-generated Sources/References/Quotes block so the code-owned
    appendix isn't duplicated. Cuts from the first standalone citation-header line
    to the end; inline ``[n]`` markers in the prose are left intact."""
    m = _MODEL_CITE_HEADER.search(answer)
    if m is None:
        return answer.rstrip()
    return answer[: m.start()].rstrip()


# Inline citation markers ("[1]", "[2, 3]") with any leading space, for plain mode.
_INLINE_CITE = re.compile(r"[ \t]*\[\d+(?:\s*,\s*\d+)*\]")


def strip_inline_citations(text: str) -> str:
    """Remove inline ``[n]`` / ``[n, m]`` markers from the prose (plain, non-debug mode)."""
    return _INLINE_CITE.sub("", text)


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
    """The verbatim Sources + Quotes appendix for the chunks the answer used.

    The quote numbers match the ``[n]`` the model wrote inline — i.e. the chunk's
    original position in the retrieved set — so a "[3]" in the prose maps to the
    "[3]" quote. When the model cited nothing, all chunks are listed in order.
    """
    if not results:
        return ""
    picked = cited_indices(answer_text, len(results))
    # (display_number, chunk) — keep the model's own numbering when it cited.
    pairs = [(i, results[i - 1]) for i in picked] if picked else list(enumerate(results, 1))

    source_lines, quote_lines, seen = [], [], set()
    for n, r in pairs:
        md = r.get("metadata", {})
        cite = f"{md.get('filename', '?')} › {md.get('section', '')}".rstrip(" ›")
        cid = md.get("chunk_id", "?")
        if cid not in seen:
            seen.add(cid)
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
