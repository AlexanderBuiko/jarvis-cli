"""
Chunking strategies.

Two interchangeable strategies, both with the signature
``(Document, *, size, overlap) -> list[Chunk]`` so they can be compared head to
head:

1. **Fixed-size** — a sliding character window of ``size`` with ``overlap``
   between consecutive windows. Simple and uniform, but blind to structure: it
   can cut mid-sentence (the lecture's caveat). ``overlap`` keeps the boundary
   "on a latch" so context isn't lost between chunks.

2. **Structure-aware** — split on Markdown headings into sections; each section
   becomes a chunk tagged with its heading path. A section longer than ``size``
   is sub-split with the same sliding window, so the section's metadata is
   preserved while no chunk grows unbounded. Plain text (no headings) degrades
   gracefully to one whole-document section, then the same sub-split.

Sizes are measured in **characters**, not tokens — the project ships no tokenizer
and characters are Unicode-safe for the mixed-language corpus. ``approx_tokens``
in the metadata uses the usual ~4-chars-per-token rule of thumb. Defaults
(``size=2000``, ``overlap=200``) land around the lecture's 500-token / ~10%-overlap
recommendation.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from .loader import Document

DEFAULT_SIZE = 2000      # characters (~500 tokens)
DEFAULT_OVERLAP = 200    # characters (~10% of a default window)
_CHARS_PER_TOKEN = 4     # rough rule of thumb, for approx_tokens only

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_ANCHOR_RE = re.compile(r"\s*\{[^}]*\}\s*$")


@dataclass
class Chunk:
    """A piece of a document plus the metadata stored alongside its embedding."""

    text: str
    metadata: dict


# ── Fixed-size ──────────────────────────────────────────────────────────────


def fixed_size_chunks(
    doc: Document,
    *,
    size: int = DEFAULT_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Sliding character window over the whole document.

    Each chunk's ``section`` is a best-effort attribution: the nearest Markdown
    heading at or before the window start (so even structure-blind chunks carry a
    meaningful section for comparison), or ``"(document start)"`` for the preamble.
    """
    headings = _heading_index(doc.text)
    chunks: list[Chunk] = []
    for idx, (piece, start, end) in enumerate(_windows(doc.text, size, overlap)):
        section = _heading_before(headings, start)
        chunks.append(_make_chunk(doc, "fixed", idx, piece, start, end, section))
    return chunks


# ── Structure-aware ─────────────────────────────────────────────────────────


def structure_aware_chunks(
    doc: Document,
    *,
    size: int = DEFAULT_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Split on Markdown headings; sub-split any section longer than ``size``."""
    sections = _split_sections(doc)
    chunks: list[Chunk] = []
    idx = 0
    for path, body, start in sections:
        if len(body) <= size:
            end = start + len(body)
            chunks.append(_make_chunk(doc, "structure", idx, body, start, end, path))
            idx += 1
            continue
        # Oversized section → sub-split, preserving the section path and offsets.
        for piece, s, e in _windows(body, size, overlap):
            chunks.append(
                _make_chunk(doc, "structure", idx, piece, start + s, start + e, path)
            )
            idx += 1
    return chunks


def _split_sections(doc: Document) -> list[tuple[str, str, int]]:
    """Break the document into (heading_path, body_text, char_start) segments.

    Each segment runs from one heading line up to the next heading of equal or
    shallower depth. Text before the first heading is attributed to the document
    title (or "(root)"). Empty segments are dropped.
    """
    text = doc.text
    lines = text.split("\n")
    root = doc.title or "(root)"

    sections: list[tuple[str, str, int]] = []
    stack: list[tuple[int, str]] = []   # (heading level, cleaned title)
    cur_path = root
    seg_start = 0
    seg_lines: list[str] = []
    char = 0

    def flush() -> None:
        body = "\n".join(seg_lines)
        if body.strip():
            sections.append((cur_path, body, seg_start))

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            title = _clean_heading(m.group(2))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            cur_path = " > ".join(t for _, t in stack) or root
            seg_start = char
            seg_lines = [line]
        else:
            seg_lines.append(line)
        char += len(line) + 1  # +1 for the "\n" that split() removed

    flush()
    return sections


# ── Shared helpers ──────────────────────────────────────────────────────────


def _windows(text: str, size: int, overlap: int) -> Iterator[tuple[str, int, int]]:
    """Yield (piece, start, end) sliding windows of ``size`` with ``overlap``.

    Whitespace-only windows are skipped. ``size``/``overlap`` are clamped so a
    degenerate config (overlap >= size) still makes forward progress.
    """
    size = max(1, size)
    step = max(1, size - max(0, overlap))
    n = len(text)
    start = 0
    while start < n:
        end = min(start + size, n)
        piece = text[start:end]
        if piece.strip():
            yield piece, start, end
        if end >= n:
            break
        start += step


def _make_chunk(
    doc: Document,
    strategy: str,
    idx: int,
    text: str,
    start: int,
    end: int,
    section: str,
) -> Chunk:
    n = len(text)
    return Chunk(
        text=text,
        metadata={
            "chunk_id": f"{doc.doc_id}:{strategy}:{idx}",
            "source": doc.source,
            "filename": doc.filename,
            "title": doc.title,
            "section": section,
            "strategy": strategy,
            "chunk_index": idx,
            "char_start": start,
            "char_end": end,
            "n_chars": n,
            "approx_tokens": round(n / _CHARS_PER_TOKEN),
        },
    )


def _clean_heading(raw: str) -> str:
    """Strip a trailing ``{ #anchor }`` and any trailing ``#`` from a heading."""
    return _ANCHOR_RE.sub("", raw).strip().rstrip("#").strip()


def _heading_index(text: str) -> list[tuple[int, str]]:
    """List of (char_offset, cleaned_title) for every heading, in order."""
    out: list[tuple[int, str]] = []
    char = 0
    for line in text.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            out.append((char, _clean_heading(m.group(1) and m.group(2))))
        char += len(line) + 1
    return out


def _heading_before(headings: list[tuple[int, str]], pos: int) -> str:
    """Title of the last heading at or before ``pos``, else "(document start)"."""
    section = "(document start)"
    for offset, title in headings:
        if offset <= pos:
            section = title
        else:
            break
    return section


# Registry so callers (CLI, pipeline, compare) select a strategy by name.
CHUNKERS = {
    "fixed": fixed_size_chunks,
    "structure": structure_aware_chunks,
}
