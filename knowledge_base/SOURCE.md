# Knowledge base — source & provenance

This folder is the test corpus for the document indexing pipeline (`index build`).
It is **external public data**, deliberately chosen so retrieval results are
meaningful and the two chunking strategies get a real workout.

## Source

- **Project:** FastAPI — <https://github.com/fastapi/fastapi>
- **Path:** `docs/en/docs/tutorial/` (the user-guide tutorial pages)
- **License:** MIT (FastAPI is MIT-licensed; these docs ship in that repo)
- **Retrieved:** 2026-06-30, from the `master` branch via
  `raw.githubusercontent.com`.

A curated subset of 24 tutorial pages was copied here unmodified. It was chosen
for **size and structure variety** — the property that makes it a good test bed
for comparing fixed-size vs. structure-aware chunking:

- Deeply nested docs (e.g. `first-steps.md`, `sql-databases.md`) — many
  `##`/`###` sections, so structure-aware chunking has rich boundaries to use.
- Flat but long docs (e.g. `query-params.md`, `body.md`) — long bodies under few
  headings, which exercise the "oversized section → sub-split" path.
- Tiny docs (e.g. `encoder.md`, `cookie-params.md`) — edge cases.

## Note

`SOURCE.md` (this file) is documentation about the corpus, not part of it. The
loader can be pointed at the folder; this file is small and harmless if indexed,
but the corpus of interest is the `*.md` tutorial pages.
