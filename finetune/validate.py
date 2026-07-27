"""Validate a training JSONL file line by line.

The assignment's required check: every line is valid JSON, every example carries
all three roles (system + user + assistant), and no content is empty. This
tool adds two project-specific checks — roles appear in order, and the assistant
label is one of the four known values — because a silently wrong label is the
one error that survives training and corrupts the eval.

Exit code is non-zero if any line fails, so it doubles as a CI gate.

Run:  python -m finetune.validate finetune/data/train.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .common import LABELS

_EXPECTED_ROLES = ("system", "user", "assistant")


def validate_line(raw: str) -> list[str]:
    """Return a list of problems with one JSONL line (empty list = valid)."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]

    messages = obj.get("messages")
    if not isinstance(messages, list):
        return ["missing 'messages' array"]

    problems: list[str] = []
    roles = [m.get("role") for m in messages if isinstance(m, dict)]
    if tuple(roles) != _EXPECTED_ROLES:
        problems.append(f"roles {roles} != {list(_EXPECTED_ROLES)}")
    for m in messages:
        if not isinstance(m, dict):
            problems.append("message is not an object")
            continue
        if not (m.get("content") or "").strip():
            problems.append(f"empty content for role {m.get('role')!r}")
    assistant = next((m.get("content", "").strip() for m in messages
                      if isinstance(m, dict) and m.get("role") == "assistant"), "")
    if assistant and assistant not in LABELS:
        problems.append(f"assistant label {assistant!r} not in {list(LABELS)}")
    return problems


def validate_file(path: Path) -> tuple[int, int, Counter]:
    """Validate every line; return (ok_count, fail_count, label_distribution)."""
    ok = fail = 0
    dist: Counter = Counter()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        problems = validate_line(raw)
        if problems:
            fail += 1
            for p in problems:
                print(f"  line {lineno}: {p}", file=sys.stderr)
        else:
            ok += 1
            label = json.loads(raw)["messages"][-1]["content"].strip()
            dist[label] += 1
    return ok, fail, dist


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a training JSONL file.")
    parser.add_argument("files", nargs="+", type=Path, help="JSONL file(s) to check")
    args = parser.parse_args(argv)

    total_fail = 0
    for path in args.files:
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            total_fail += 1
            continue
        ok, fail, dist = validate_file(path)
        total_fail += fail
        bal = ", ".join(f"{lbl}={dist.get(lbl, 0)}" for lbl in LABELS)
        status = "OK" if fail == 0 else f"{fail} FAILED"
        print(f"{path}: {ok} valid, {status}  [{bal}]")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
