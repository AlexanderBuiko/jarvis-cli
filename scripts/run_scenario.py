"""
Scenario runner — drives JarvisAgent with a predefined sequence of messages.

Usage:
    python scripts/run_scenario.py <scenario.json>

Scenario file format:
    {
        "thread": "optional-thread-name",
        "config": {
            "context_strategy": "topics",
            "model": "qwen/qwen3-32b"
        },
        "messages": [
            "Tell me about Android architecture",
            "What about MVVM specifically?",
            "Now let's talk about my job search"
        ]
    }

All keys except "messages" are optional.
The runner creates a new named thread for the scenario so results are
inspectable afterwards via 'thread load <name>' in the normal REPL.
At the end the full thread summary is printed.
"""

import json
import sys
import time
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.config.manager import ConfigManager
from jarvis.openrouter.client import OpenRouterClient, DEFAULT_MODEL
from jarvis.agent import JarvisAgent
from jarvis.repl.commands import handle_thread_summary


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_scenario.py <scenario.json>", file=sys.stderr)
        sys.exit(1)

    scenario_path = Path(sys.argv[1])
    if not scenario_path.exists():
        print(f"File not found: {scenario_path}", file=sys.stderr)
        sys.exit(1)

    try:
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in scenario file: {exc}", file=sys.stderr)
        sys.exit(1)

    messages = scenario.get("messages")
    if not messages or not isinstance(messages, list):
        print("Scenario must contain a non-empty 'messages' list.", file=sys.stderr)
        sys.exit(1)

    # ── Bootstrap ──────────────────────────────────────────────────────────────

    try:
        config_manager = ConfigManager()
        client = OpenRouterClient()
    except EnvironmentError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(1)

    agent = JarvisAgent(client, config_manager)

    # Create a dedicated thread for this scenario run.
    thread_name = scenario.get("thread") or f"scenario-{scenario_path.stem}"
    agent.new_thread(thread_name)
    print(f"Thread: '{thread_name}'\n")

    # Apply scenario config (must be done on the empty thread).
    config = scenario.get("config") or {}
    for key, value in config.items():
        try:
            config_manager.set(key, str(value))
            print(f"config {key} = {value}")
        except (ValueError, TypeError) as exc:
            print(f"Warning: could not set {key}={value}: {exc}", file=sys.stderr)
    if config:
        print()

    sep = "─" * 60

    # ── Message loop ───────────────────────────────────────────────────────────

    for i, user_message in enumerate(messages, start=1):
        print(sep)
        print(f"[{i}/{len(messages)}] You: {user_message}")
        print()

        t0 = time.monotonic()
        try:
            response = agent.chat(user_message)
        except Exception as exc:
            print(f"Error on message {i}: {exc}", file=sys.stderr)
            sys.exit(1)
        elapsed = time.monotonic() - t0

        print(f"Jarvis ({elapsed:.1f}s): {response}")
        print()

    # ── Thread summary ─────────────────────────────────────────────────────────

    print(sep)
    model = config_manager.runtime.get("model") or DEFAULT_MODEL
    ctx = agent.get_context_window(model)
    print(handle_thread_summary(agent, ctx))


if __name__ == "__main__":
    main()
