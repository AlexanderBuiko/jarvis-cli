"""Lay out the dataset the way ``mlx_lm.lora`` expects.

The OpenAI ``upload_client`` is dead for us (OpenAI is blocked), so the local
fine-tune replaces it. ``mlx_lm.lora`` reads a directory of ``train.jsonl`` /
``valid.jsonl`` / ``test.jsonl`` in chat format — which is exactly what
``train.jsonl`` / ``eval.jsonl`` already are (``{"messages": [...]}``). This just
copies them into that layout and re-validates, so the tuner never sees a
malformed line. ``valid`` and ``test`` both point at the eval split (we only have
one held-out set; the tuner watches ``valid`` during training and ``--test``
scores the same rows at the end).

Run:  python -m finetune.mlx_prepare
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import LABELS

_DATA = Path(__file__).parent / "data"
_OUT = Path(__file__).parent / "mlx_data"


def _validate_and_copy(src: Path, dst: Path) -> int:
    """Copy a chat-format JSONL line by line, raising on the first bad row."""
    lines = [ln for ln in src.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        obj = json.loads(line)
        roles = [m.get("role") for m in obj.get("messages", [])]
        if roles != ["system", "user", "assistant"]:
            raise ValueError(f"{src}:{i}: roles {roles} != system/user/assistant")
        if obj["messages"][-1]["content"].strip() not in LABELS:
            raise ValueError(f"{src}:{i}: assistant label not in {LABELS}")
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the mlx_lm.lora data dir.")
    parser.add_argument("--train", type=Path, default=_DATA / "train.jsonl")
    parser.add_argument("--eval", type=Path, default=_DATA / "eval.jsonl")
    parser.add_argument("--out", type=Path, default=_OUT)
    args = parser.parse_args(argv)

    for path in (args.train, args.eval):
        if not path.exists():
            print(f"error: {path} not found — run the Day-6 split first")
            return 2

    args.out.mkdir(parents=True, exist_ok=True)
    n_train = _validate_and_copy(args.train, args.out / "train.jsonl")
    n_valid = _validate_and_copy(args.eval, args.out / "valid.jsonl")
    _validate_and_copy(args.eval, args.out / "test.jsonl")
    print(f"wrote {args.out}/ : train={n_train}, valid={n_valid}, test={n_valid}")
    print("next: mlx_lm.lora --train --data", args.out, "(see finetune/README.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
