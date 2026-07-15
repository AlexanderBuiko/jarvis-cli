"""
Entrypoint for the reactive PR reviewer: ``python -m jarvis.review``.

In CI, run it with no args — it reads the PR context from the GitHub Action
environment. Locally, pass ``--base``/``--head`` and ``--dry-run`` to exercise the
whole flow without posting to a real PR.
"""

from __future__ import annotations

import argparse
import sys

from .client import ReviewClientError, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jarvis.review",
                                     description="Reactive AI PR code review.")
    parser.add_argument("--base", help="git ref to diff against (default: PR base / origin/main)")
    parser.add_argument("--head", help="git ref of the PR head (default: HEAD)")
    parser.add_argument("--repo", help='owner/name (default: $GITHUB_REPOSITORY)')
    parser.add_argument("--pr", type=int, help="PR number (default: from the Action event)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the comment instead of posting (also via DRY_RUN=1)")
    args = parser.parse_args(argv)

    try:
        status = run(base=args.base, head=args.head, repo=args.repo, pr=args.pr,
                     dry_run=True if args.dry_run else None)
    except ReviewClientError as exc:
        print(f"review failed: {exc}", file=sys.stderr)
        return 1
    print(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
