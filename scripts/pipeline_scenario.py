"""
Pipeline scenario — the interactive task driver, run non-interactively.

Demonstrates the gate model: the pipeline rolls forward on its own and pauses
only at gates — free-text questions (clarification / execution) and the two
Confirm/Reject approvals (plan approval, final done). Here those gates are
answered programmatically (auto-confirm; canned answers) so the whole flow runs
end to end without a human.

Usage:
    python scripts/pipeline_scenario.py

Requires OPENROUTER_API_KEY (real LLM calls).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.config.manager import ConfigManager
from jarvis.openrouter.client import OpenRouterClient
from jarvis.agent import JarvisAgent
from jarvis.pipeline.base import GATE_APPROVAL, GATE_QUESTION

SEP = "─" * 66
_MAX_TURNS = 40


def auto_drive(agent: JarvisAgent, answers: list[str]) -> None:
    """Drive the active task to done, auto-confirming approvals and feeding answers."""
    answers = list(answers)
    pending = ""
    for _ in range(_MAX_TURNS):
        feedback, pending = pending, ""
        result = agent.pipeline_step(feedback)
        if result is None or result.blocked:
            print(f"  (stopped: {result.blocked if result else 'no task'})")
            return
        arrow = f" → {result.advanced_to}" if result.advanced_to else ""
        print(f"\n[{result.stage}]{arrow}\n{result.text}")

        verdict = result.verdict
        if verdict.gate == GATE_APPROVAL:
            print("  ▸ auto-Confirm")
            agent.advance_to(verdict.confirm_target)
        elif verdict.gate == GATE_QUESTION:
            answer = answers.pop(0) if answers else "Proceed with sensible defaults."
            print(f"  ▸ You: {answer}")
            pending = f"The user responded: {answer}"
        elif agent.active_task and agent.active_task["stage"] == "done":
            print("\n✓ Task complete.")
            return


def main() -> None:
    try:
        config = ConfigManager()
        client = OpenRouterClient()
    except EnvironmentError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(1)

    config.set("seed", "42")  # reproducibility
    agent = JarvisAgent(client, config)

    agent.new_thread("pipeline-demo")
    task = agent.create_task("packing_list")
    print(SEP)
    print(f"Thread = '{agent.thread_name}'   Task = {task['name']} ({task['id']})")
    print("Gates: free-text questions + Confirm/Reject at plan approval and done.")
    print(SEP)

    auto_drive(
        agent,
        answers=[
            # Answer for the clarification question gate:
            "Make a 3-item packing list for a weekend hiking trip. Plan = 3 numbered "
            "steps, one per item. Execution produces each item. Done when there are "
            "exactly 3 hiking-appropriate items.",
        ],
    )

    print("\n" + SEP)
    print("The pipeline advanced through the stages by itself, pausing only at gates;")
    print("every stage transition still went through the code-enforced FSM.")
    print(SEP)


if __name__ == "__main__":
    main()
