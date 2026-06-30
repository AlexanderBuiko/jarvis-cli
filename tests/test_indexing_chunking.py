"""Tests for the two chunking strategies (jarvis.indexing.chunking)."""

import unittest

from jarvis.indexing.chunking import (
    fixed_size_chunks,
    structure_aware_chunks,
    CHUNKERS,
)
from jarvis.indexing.loader import Document

REQUIRED_META = {"source", "filename", "title", "section", "chunk_id"}

MARKDOWN = """# Guide Title

Intro paragraph before any subheading.

## Section One

Body of section one with some words.

### Subsection A

Nested content under section one.

## Section Two

Body of section two.
"""


def _doc(text: str, doc_id: str = "guide", title: str = "Guide Title") -> Document:
    return Document(
        doc_id=doc_id, source=f"/kb/{doc_id}.md",
        filename=f"{doc_id}.md", title=title, text=text,
    )


class FixedSizeTest(unittest.TestCase):
    def test_window_sizes_and_required_metadata(self):
        text = "".join(f"line {i}\n" for i in range(400))  # ~3200 chars
        chunks = fixed_size_chunks(_doc(text), size=1000, overlap=100)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(c.metadata["n_chars"], 1000)
            self.assertTrue(REQUIRED_META.issubset(c.metadata))
            self.assertEqual(c.metadata["strategy"], "fixed")

    def test_overlap_repeats_boundary_text(self):
        text = "abcdefghijklmnopqrstuvwxyz" * 100  # 2600 chars
        chunks = fixed_size_chunks(_doc(text), size=1000, overlap=200)
        # Consecutive windows step by size-overlap=800; the tail of chunk 0 must
        # reappear at the head of chunk 1 (boundary "on a latch").
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].text[800:1000], chunks[1].text[:200])

    def test_chunk_ids_are_unique_and_ordered(self):
        text = "word " * 1000
        chunks = fixed_size_chunks(_doc(text), size=500, overlap=50)
        ids = [c.metadata["chunk_id"] for c in chunks]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "guide:fixed:0")

    def test_section_attributes_nearest_heading(self):
        chunks = fixed_size_chunks(_doc(MARKDOWN), size=60, overlap=0)
        sections = {c.metadata["section"] for c in chunks}
        # Best-effort heading attribution should surface real headings.
        self.assertTrue(any(s in sections for s in ("Section One", "Section Two")))


class StructureAwareTest(unittest.TestCase):
    def test_splits_on_headings_with_heading_path(self):
        chunks = structure_aware_chunks(_doc(MARKDOWN), size=2000, overlap=0)
        sections = [c.metadata["section"] for c in chunks]
        # Heading path is the full breadcrumb from the H1 down, joined by " > ".
        self.assertIn("Guide Title > Section One", sections)
        self.assertTrue(any(s.endswith(" > Subsection A") for s in sections))
        for c in chunks:
            self.assertTrue(REQUIRED_META.issubset(c.metadata))
            self.assertEqual(c.metadata["strategy"], "structure")

    def test_oversized_section_is_subsplit_keeping_section(self):
        big = "# Doc\n\n## Big\n\n" + ("filler words here " * 400)  # one huge section
        chunks = structure_aware_chunks(_doc(big), size=500, overlap=50)
        big_chunks = [c for c in chunks if c.metadata["section"].endswith("Big")]
        self.assertGreater(len(big_chunks), 1)  # sub-split happened
        for c in big_chunks:
            self.assertLessEqual(c.metadata["n_chars"], 500)

    def test_plaintext_without_headings_degrades_gracefully(self):
        chunks = structure_aware_chunks(_doc("just some plain text\nno headings here"))
        self.assertEqual(len(chunks), 1)
        self.assertTrue(REQUIRED_META.issubset(chunks[0].metadata))

    def test_unicode_corpus_is_handled(self):
        text = "# Заголовок\n\nЭто текст на русском языке про эмбеддинги.\n"
        chunks = structure_aware_chunks(_doc(text, title="Заголовок"))
        self.assertEqual(chunks[0].metadata["section"], "Заголовок")
        self.assertIn("русском", chunks[0].text)


class RegistryTest(unittest.TestCase):
    def test_registry_exposes_both_strategies(self):
        self.assertEqual(set(CHUNKERS), {"fixed", "structure"})


if __name__ == "__main__":
    unittest.main()
