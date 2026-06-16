"""
Long-term-memory A/B demo — shows how the SAME request gets a different answer
once profile + invariants are injected into the system prompt.

It asks one question twice, with the same model and seed, changing only one
thing between the two runs:

    Run A — empty long-term memory  → base system prompt
    Run B — profile.md + invariants.md present → they are injected into the
            system prompt for every request (and invariants are also enforced
            in code: a violating reply is reworked before you see it)

The profile here makes the style terse + bilingual-beginner, and the invariant
forces Spanish — both effects are easy to see in the output.

A throwaway temp directory is used for memory, so your real ~/.jarvis/memory/
files are left untouched.

Usage:
    python scripts/ltm_compare.py

Requires OPENROUTER_API_KEY (real LLM calls, like run_scenario.py).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.config.manager import ConfigManager
from jarvis.openrouter.client import OpenRouterClient
from jarvis.agent import JarvisAgent
from jarvis.session.long_term_memory import LongTermMemory

SEP = "─" * 70

PROMPT = "Give me a few tips to stay motivated to study every day."

PROFILE_MD = """\
# Profile

## Style
- Answer in at most 3 short bullet points; use simple, encouraging language.

## Context
- I am a beginner and get overwhelmed by long, detailed answers.
"""

INVARIANTS_MD = """\
# Invariants

- Always reply in Spanish, regardless of the language the question is asked in.
"""


def run(agent: JarvisAgent, label: str, thread: str) -> None:
    agent.new_thread(thread)
    print("\n" + SEP)
    print(label)
    print(SEP)
    print(f"You: {PROMPT}\n")
    print(f"Jarvis: {agent.chat(PROMPT)}")


def main() -> None:
    try:
        config = ConfigManager()
        client = OpenRouterClient()
    except EnvironmentError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(1)

    config.set("seed", "42")  # same seed both runs → only the prompt differs
    agent = JarvisAgent(client, config)

    # Isolate memory in a temp dir so the real ~/.jarvis/memory/ is untouched.
    mem_dir = Path(tempfile.mkdtemp(prefix="jarvis-ltm-")) / "memory"
    agent._memory = LongTermMemory(mem_dir)

    # ── Run A: no long-term memory ───────────────────────────────────────────
    run(agent, "WITHOUT long-term memory (empty profile / invariants)", "ltm-without")

    # ── Run B: profile + invariants present ──────────────────────────────────
    agent._memory.write("profile", PROFILE_MD)
    agent._memory.write("invariants", INVARIANTS_MD)
    print("\n" + SEP)
    print("Injecting long-term memory for the next run:")
    print(SEP)
    print("profile.md:\n" + PROFILE_MD)
    print("invariants.md:\n" + INVARIANTS_MD)

    run(agent, "WITH long-term memory (profile + invariants injected)", "ltm-with")

    print("\n" + SEP)
    print("Same prompt, same seed. Run A is the base behaviour; Run B is shaped by")
    print("the always-on profile (terse, beginner-friendly bullets) and invariant")
    print("(replies in Spanish, enforced in both prompt and code).")
    print(SEP)


if __name__ == "__main__":
    main()
