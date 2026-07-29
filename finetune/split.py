"""Clean, merge and split the dataset into train (80%) / eval (20%).

Step 4. Takes one or more JSONL inputs (real + synthetic), removes the trash the
assignment calls out — duplicates, empty, too short, too long — then does a
*stratified* 80/20 split so every label is represented in both halves in the
same proportion. A plain random split can starve a small class from eval
entirely; stratifying is what keeps the 10-example baseline meaningful.

Deterministic: a fixed seed means the same split every run, so baseline and
fine-tune are compared on identical eval rows.

Run:  python -m finetune.split finetune/data/real.jsonl finetune/data/synthetic.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from .common import LABELS

_DATA = Path(__file__).parent / "data"
_MIN_CHARS = 5     # shorter than this is noise, not a message
_MAX_CHARS = 6000  # longer than this bloats a classification example
_DIGITS = re.compile(r"\d+")


def _dedup_key(text: str) -> str:
    """Whitespace- and digit-normalised key.

    Masking digit runs collapses *near*-duplicates that differ only by a number —
    the same Aviasales price alert at $611/$612/$623, the "you have N new
    messages" notifications. Keeping all of them would be the duplication
    antipattern, and splitting siblings across train/eval would leak and inflate
    the eval score. One representative per template is what we want.
    """
    return _DIGITS.sub("#", " ".join(text.lower().split()))


def _user_text(obj: dict) -> str:
    return next((m["content"] for m in obj["messages"] if m["role"] == "user"), "")


def _label(obj: dict) -> str:
    return obj["messages"][-1]["content"].strip()


def clean(objects: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Drop duplicates and out-of-range messages; return (kept, drop-counts)."""
    seen: set[str] = set()
    kept: list[dict] = []
    dropped = {"duplicate": 0, "empty": 0, "too_short": 0, "too_long": 0}
    for obj in objects:
        text = _user_text(obj).strip()
        key = _dedup_key(text)
        if not text:
            dropped["empty"] += 1
        elif len(text) < _MIN_CHARS:
            dropped["too_short"] += 1
        elif len(text) > _MAX_CHARS:
            dropped["too_long"] += 1
        elif key in seen:
            dropped["duplicate"] += 1
        else:
            seen.add(key)
            kept.append(obj)
    return kept, dropped


def stratified_split(objects: list[dict], eval_frac: float, seed: int) -> tuple[list[dict], list[dict]]:
    """Split per-label so both halves keep the label mix; eval gets >=1 per label present."""
    rng = random.Random(seed)
    by_label: dict[str, list[dict]] = defaultdict(list)
    for obj in objects:
        by_label[_label(obj)].append(obj)

    train: list[dict] = []
    eval_: list[dict] = []
    for label in sorted(by_label):
        group = by_label[label]
        rng.shuffle(group)
        n_eval = max(1, round(len(group) * eval_frac)) if len(group) > 1 else 0
        eval_.extend(group[:n_eval])
        train.extend(group[n_eval:])
    rng.shuffle(train)
    rng.shuffle(eval_)
    return train, eval_


def _write(path: Path, objects: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for obj in objects:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _load(paths: list[Path]) -> list[dict]:
    objects: list[dict] = []
    for path in paths:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                objects.append(json.loads(raw))
    return objects


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean + stratified 80/20 split.")
    parser.add_argument("inputs", nargs="+", type=Path, help="JSONL file(s) to merge")
    parser.add_argument("--eval-frac", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--train-out", type=Path, default=_DATA / "train.jsonl")
    parser.add_argument("--eval-out", type=Path, default=_DATA / "eval.jsonl")
    args = parser.parse_args(argv)

    missing = [p for p in args.inputs if not p.exists()]
    if missing:
        print(f"error: not found: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 2

    objects = _load(args.inputs)
    kept, dropped = clean(objects)
    train, eval_ = stratified_split(kept, args.eval_frac, args.seed)
    _write(args.train_out, train)
    _write(args.eval_out, eval_)

    print(f"loaded {len(objects)}, dropped {sum(dropped.values())} "
          f"({', '.join(f'{k}={v}' for k, v in dropped.items() if v)})")
    for name, split in (("train", train), ("eval", eval_)):
        counts = {lbl: sum(1 for o in split if _label(o) == lbl) for lbl in LABELS}
        bal = ", ".join(f"{lbl}={counts[lbl]}" for lbl in LABELS)
        print(f"{name}: {len(split)}  [{bal}]  -> {args.train_out if name == 'train' else args.eval_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
