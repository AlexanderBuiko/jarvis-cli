"""
Document loading.

Reads UTF-8 text documents (``.md``/``.txt``) from a single file or, recursively,
from a directory. Binary, unreadable, or empty files are skipped rather than
crashing the build. Each ``Document`` carries the raw text plus the provenance the
chunkers turn into per-chunk metadata (source, filename, title).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Suffixes treated as indexable text. Markdown first — it carries the heading
# structure the structure-aware chunker relies on.
TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
# Markdown heading anchors like "# Title { #slug }" — strip the trailing braces.
_ANCHOR_RE = re.compile(r"\s*\{[^}]*\}\s*$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class Document:
    """One loaded source document, before chunking."""

    doc_id: str   # stable slug derived from the filename (unique within a load)
    source: str   # path as given — used for citations / source links
    filename: str
    title: str    # first H1 heading if present, else the filename stem
    text: str


def load_documents(
    path: str | Path,
    suffixes: frozenset[str] = TEXT_SUFFIXES,
) -> list[Document]:
    """Load indexable documents from a file or directory.

    A directory is scanned recursively for files whose suffix is in ``suffixes``.
    Files that can't be read as UTF-8 (binary) or are empty after stripping are
    skipped. Raises ``FileNotFoundError`` if the path doesn't exist.
    """
    root = Path(path)
    if root.is_file():
        files = [root]
    elif root.is_dir():
        files = sorted(
            f for f in root.rglob("*")
            if f.is_file() and f.suffix.lower() in suffixes
        )
    else:
        raise FileNotFoundError(f"No such file or directory: {path}")

    docs: list[Document] = []
    seen_ids: dict[str, int] = {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # skip binary / unreadable
        if not text.strip():
            continue
        doc_id = _unique_id(_slug(f.stem), seen_ids)
        docs.append(Document(
            doc_id=doc_id,
            source=str(f),
            filename=f.name,
            title=_extract_title(text, f.stem),
            text=text,
        ))
    return docs


def _extract_title(text: str, fallback: str) -> str:
    """First H1 heading (anchor stripped), else the filename stem."""
    m = _H1_RE.search(text)
    if m:
        return _ANCHOR_RE.sub("", m.group(1)).strip() or fallback
    return fallback


def _slug(stem: str) -> str:
    slug = _SLUG_RE.sub("-", stem.lower()).strip("-")
    return slug or "doc"


def _unique_id(base: str, seen: dict[str, int]) -> str:
    """Disambiguate stems that collide across subdirectories (base, base-2, …)."""
    if base not in seen:
        seen[base] = 1
        return base
    seen[base] += 1
    return f"{base}-{seen[base]}"
