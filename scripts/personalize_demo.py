"""
Personalisation demo — a real end-to-end run of the `personalize` command.

Flow:
  1. Show the starting profile.md.
  2. Open a fresh thread and ask several real questions whose phrasing
     consistently signals one style preference (short, bullet-point answers).
     Each real turn is recorded in the behaviour log automatically.
  3. Run `personalize`: the refiner reads the behaviour log and proposes a new
     '## Style' section (one LLM call). We print current vs proposed.
  4. Apply it and print the resulting profile.md — only the Style block changes;
     Constraints and Context are preserved verbatim.

Throwaway temp dirs are used for the memory files and the behaviour log, so your
real ~/.jarvis/ is left untouched.

Usage:
    python scripts/personalize_demo.py

Requires OPENROUTER_API_KEY (real LLM calls: one per question + one to refine).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.config.manager import ConfigManager
from jarvis.openrouter.client import OpenRouterClient
from jarvis.agent import JarvisAgent
from jarvis.session.profile_store import ProfileStore
from jarvis.session.behavior_log import BehaviorLog

SEP = "─" * 70

# Initial profile: a vague Style, but concrete Constraints + Context to preserve.
PROFILE_MD = """\
# Profile

## Style
- (no preference recorded yet)

## Constraints
- Use only free, open-source tools.

## Context
- I am a backend engineer using Jarvis while pair-programming.
"""

# Real questions to ask. Their phrasing consistently asks for short, bulleted,
# example-light answers — a style signal the refiner can pick up from behaviour.
QUESTIONS = [
    "In one short sentence: what is a database index?",
    "Give me just 3 bullet points on when to use a message queue.",
    "Briefly, no preamble: difference between a process and a thread?",
    "TL;DR only: what does idempotent mean for an API?",
    "One line each, max 3 bullets: tips to keep a REST API backward compatible.",
]


def truncate(text: str, limit: int = 200) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main() -> None:
    try:
        config = ConfigManager()
        client = OpenRouterClient()
    except EnvironmentError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(1)

    agent = JarvisAgent(client, config)

    # Isolate profile + behaviour log in temp dirs (real ~/.jarvis untouched).
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-personalize-"))
    (tmp / "memory").mkdir(parents=True, exist_ok=True)
    agent._profile = ProfileStore(tmp / "memory")
    agent._behavior = BehaviorLog(tmp / "behavior.jsonl")
    agent._profile.write(PROFILE_MD)

    # ── 1. Show the starting profile ─────────────────────────────────────────
    print(SEP)
    print("1. Starting profile.md")
    print(SEP)
    print(agent.read_profile())

    # ── 2. New thread + several real questions ───────────────────────────────
    agent.new_thread("personalize-demo")
    print(SEP)
    print(f"2. New thread '{agent.thread_name}': asking {len(QUESTIONS)} questions")
    print(SEP)
    for i, q in enumerate(QUESTIONS, 1):
        answer = agent.chat(q)
        print(f"\n[Q{i}] You: {q}")
        print(f"      Jarvis: {truncate(answer)}")

    # ── 3. Run `personalize`: propose a new Style from the behaviour log ──────
    current, proposed, error = agent.propose_profile_style()
    print("\n" + SEP)
    print("3. `personalize` — proposed Style update from recent activity")
    print(SEP)
    if error:
        print(error)
        return
    if proposed is None:
        print("Recent activity didn't warrant a style change — profile.md left as is.")
        return
    print(f"Current Style\n{'-' * 30}\n{(current or '(empty)').strip()}\n")
    print(f"Proposed Style\n{'-' * 30}\n{proposed.strip()}")

    # In the REPL this is gated on a [y/N]; here we apply it to show the result.
    agent.apply_profile_style(proposed)

    # ── 4. Show the updated profile ──────────────────────────────────────────
    print("\n" + SEP)
    print("4. Updated profile.md (only the Style section changed)")
    print(SEP)
    print(agent.read_profile())

    print(SEP)
    print("Constraints (free/open-source) and Context (backend engineer) are")
    print("preserved verbatim — the refiner only ever rewrites the Style block.")
    print(SEP)


if __name__ == "__main__":
    main()
