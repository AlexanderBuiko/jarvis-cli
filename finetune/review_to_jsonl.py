"""Convert your labelled ``review.json`` into training-format JSONL.

Step 3a. Reads the file you curated (rows with a real ``label``), skips any row
still blank or carrying an unknown label, and writes one training object per
line via the shared ``training_object`` transform. This is the *real* slice;
synthetic examples are appended later in the same format.

Run:  python -m finetune.review_to_jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import LABELS, sanitize, training_object

_DATA = Path(__file__).parent / "data"


def convert(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Return (training objects, warnings) — skipping unlabelled/invalid rows."""
    objects: list[dict] = []
    warnings: list[str] = []
    for i, row in enumerate(rows):
        label = (row.get("label") or "").strip()
        topic = sanitize((row.get("topic") or "").strip())
        author = sanitize((row.get("author") or "").strip())
        message = sanitize((row.get("message") or "").strip())
        if not label:
            continue  # deliberately left blank = you excluded it
        if label not in LABELS:
            warnings.append(f"row {i}: unknown label {label!r}, skipped")
            continue
        if not message:
            warnings.append(f"row {i}: empty message after sanitising, skipped")
            continue
        objects.append(training_object(topic, author, message, label))
    return objects, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Labelled review.json → training JSONL.")
    parser.add_argument("--in", dest="src", type=Path, default=_DATA / "review.json")
    parser.add_argument("--out", type=Path, default=_DATA / "real.jsonl")
    args = parser.parse_args(argv)

    if not args.src.exists():
        print(f"error: {args.src} not found — run extract_messages first", file=sys.stderr)
        return 2
    rows = json.loads(args.src.read_text(encoding="utf-8"))
    objects, warnings = convert(rows)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if not objects:
        print("error: no labelled rows found — fill in some labels first", file=sys.stderr)
        return 1

    with args.out.open("w", encoding="utf-8") as fh:
        for obj in objects:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"wrote {len(objects)} real examples to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
