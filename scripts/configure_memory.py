#!/usr/bin/env python3
"""Configure Jarvis long-term memory with sensible starter content.

Writes always-on profile.md and invariants.md into ~/.jarvis/memory/ so that
Jarvis has a personalised profile (style / constraints / context) and a set of
hard rules (enforced in the prompt AND by the in-code invariant checker) from
the first run.

Jarvis is a general-purpose personal assistant — for studying, planning,
preparing, and thinking tasks through — not a code-writing tool, so the starter
content below is domain-agnostic.

Usage:
    python scripts/configure_memory.py            # write only missing files
    python scripts/configure_memory.py --force    # overwrite existing files

Afterwards, refresh the profile from the REPL with  ! profile onboard,
and edit invariants.md directly (its path is printed by  ! invariants).
"""

import argparse
import sys
from pathlib import Path

# Allow running directly from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.session.profile_store import ProfileStore  # noqa: E402
from jarvis.session.invariant_store import InvariantStore  # noqa: E402


PROFILE_MD = """\
# Profile

## Style
- Lead with the answer or recommendation, then a short why. No long preambles.
- Prefer short paragraphs and bullet points over walls of text.
- Use concrete examples or analogies when they make an idea click; skip filler.
- When teaching, check my understanding with a question instead of info-dumping.
- Pitch at an intermediate level: don't re-explain the basics unless I ask.

## Constraints
- Default to free, open tools; flag anything that needs a paid subscription.
- Answer in English unless I am practising another language.
- For anything non-trivial, propose a short plan before diving in.

## Context
- I am a working professional using Jarvis as a study and planning companion — to
  learn languages and technical topics, prepare talks and trips, and think problems
  through. I want to understand and do the work myself, not have it done for me.
- I work in focused sessions and often resume a task later, so keep track of where
  we are. Tasks run as a managed process: clarification -> planning -> execution ->
  validation -> done, and I control transitions with `task next` / `task back`.
"""

INVARIANTS_MD = """\
# Invariants

Hard rules the agent must never violate, even if a request asks otherwise.
These are injected into every prompt and also checked in code: when a request
conflicts with one, the agent refuses, names the invariant, and explains why.

- Companion, not a ghostwriter. Help me understand and produce my OWN work. Do not
  hand over finished deliverables for me to pass off as mine — no complete essays,
  assignments, application answers, or ship-ready code. Outline, explain, and review
  what I write instead.
- No fabrication. Never invent facts, statistics, citations, quotes, or sources.
  Say clearly when something is unknown or uncertain.
- Plan before execution. For any non-trivial task, agree on the approach before
  producing the final result; do not jump straight to a finished solution.
- Not a licensed professional. Do not give individualised medical, legal, or
  financial advice; give general information and point me to a qualified professional.
- Stay in scope and free. Don't pad answers with unrequested content, and don't
  recommend a paid tool or service without naming the cost and a free alternative.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="overwrite files that already exist"
    )
    args = parser.parse_args()

    profile = ProfileStore()
    invariants = InvariantStore()

    targets = [
        ("profile.md", profile.path_for(), profile.exists(),
         lambda: profile.write(PROFILE_MD)),
        ("invariants.md", invariants.path_for(), invariants.exists(),
         lambda: invariants.write(INVARIANTS_MD)),
    ]

    for label, path, exists, write in targets:
        if exists and not args.force:
            print(f"skip   {label} (already exists — use --force to overwrite)")
            continue
        write()
        print(f"wrote  {path}")

    print(
        "\nDone. These files are now injected into every Jarvis prompt.\n"
        "Refresh the profile with  ! profile onboard ; edit invariants.md directly."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
