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

Afterwards, edit them any time from the REPL:
    ! memory edit profile
    ! memory edit invariants
"""

import argparse
import sys
from pathlib import Path

# Allow running directly from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.session.long_term_memory import LongTermMemory  # noqa: E402


PROFILE_MD = """\
# Profile

## Style
- Be concise: lead with the answer, then a short justification.
- Use concrete examples or analogies when they aid understanding; skip filler.
- When teaching or explaining, check my understanding rather than info-dumping.

## Constraints
- Stay within the scope of what I asked; flag clearly when something is out of scope.
- Adapt the depth to my stated level; don't over-simplify or over-complicate.
- (Add your own: preferred language, topics of interest, level of detail.)

## Context
- I use Jarvis as a general-purpose personal assistant — for studying, planning,
  preparing for things, and thinking tasks through. Not for writing code.
- Tasks run as a managed process: clarification -> planning -> execution ->
  validation -> done, and I control stage transitions with `task next` / `task back`.
"""

INVARIANTS_MD = """\
# Invariants

Hard rules the agent must never violate, even if a request asks otherwise.
These are injected into every prompt and also checked in code: a reply that
breaks one is automatically reworked before it reaches me.

- Never invent facts, sources, numbers, or quotes — say clearly when something
  is unknown or uncertain.
- Ask a clarifying question before giving a definitive answer to an ambiguous request.
- Stay within the scope I asked for; don't pad answers with unrequested content.
- (Add your own domain rules, e.g. preferred language, study goals, topics to avoid.)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="overwrite files that already exist"
    )
    args = parser.parse_args()

    memory = LongTermMemory()
    files = {"profile": PROFILE_MD, "invariants": INVARIANTS_MD}

    for name, content in files.items():
        path = memory.path_for(name)
        if memory.exists(name) and not args.force:
            print(f"skip   {name}.md (already exists — use --force to overwrite)")
            continue
        memory.write(name, content)
        print(f"wrote  {path}")

    print(
        "\nDone. These files are now injected into every Jarvis prompt.\n"
        "Edit them from the REPL with:  ! memory edit profile  /  ! memory edit invariants"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
