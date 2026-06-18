"""
Task scenario — a standalone task workspace, exited and re-entered.

A task is independent of chat threads and carries its own conversation. This demo
drives a task into execution, EXITS it (back to chat), then RE-ENTERS it later and
finishes — showing the task resumes from its own preserved state and transcript.

Usage:
    python scripts/task_scenario.py

Requires OPENROUTER_API_KEY (real LLM calls, like run_scenario.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.config.manager import ConfigManager
from jarvis.openrouter.client import OpenRouterClient
from jarvis.agent import JarvisAgent
from jarvis.pipeline.base import GATE_APPROVAL, GATE_QUESTION
from jarvis.repl.loop import _split_summary

SEP = "─" * 66


def _drive(agent: JarvisAgent, answers: list[str], stop_at_stage: str | None = None) -> None:
    """Drive the active task, auto-confirming approvals and feeding canned answers.

    Stops when the task reaches stop_at_stage (so the demo can switch threads
    mid-task), or when it is done.
    """
    answers = list(answers)
    pending = ""
    for _ in range(40):
        if stop_at_stage and agent.active_task and agent.active_task["stage"] == stop_at_stage:
            return
        feedback, pending = pending, ""
        result = agent.pipeline_step(feedback)
        if result is None or result.blocked:
            print(f"  (stopped: {result.blocked if result else 'no task'})")
            return
        arrow = f" → {result.advanced_to}" if result.advanced_to else ""
        print(f"\n[{agent.thread_name}][{result.stage}]{arrow}\n{result.text}")
        verdict = result.verdict
        if verdict.gate == GATE_APPROVAL:
            print("  ▸ auto-Confirm")
            agent.advance_to(verdict.confirm_target)
        elif verdict.gate == GATE_QUESTION:
            answer = answers.pop(0) if answers else "Proceed with sensible defaults."
            print(f"  ▸ You: {answer}")
            pending = f"The user responded: {answer}"
        elif agent.active_task and agent.active_task["stage"] == "done":
            summary, deliverable = _split_summary(result.text)
            path = agent.save_task_result(deliverable)
            print(f"\n✓ Task complete: {summary}\n   Result saved to {path}")
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

    # ── Enter the task and drive it into execution ───────────────────────────
    task = agent.create_task("spanish_phrases")
    print(SEP)
    print(f"Entered task = {task['name']} ({task['id']})   (independent of any thread)")
    print(SEP)

    _drive(
        agent,
        answers=[
            "Help me memorise exactly 3 Spanish travel phrases: 'hello', 'thank you', "
            "and 'where is the bathroom?'. Plan = 3 numbered steps, one phrase each. "
            "Execution shows each phrase with its translation. Done when I can recall all three.",
        ],
        stop_at_stage="validation",   # leave before finishing, to demo re-entry
    )

    # ── Exit to chat, then re-enter the task to finish it ────────────────────
    left = agent.exit_task()
    print("\n" + SEP)
    print(f"! task exit   → left '{left}', back in chat mode")
    agent.start_task("spanish_phrases")
    print(f"! task start spanish_phrases   → re-entered at stage '{agent.active_task['stage']}'")
    print(SEP)

    # The task resumes from its own preserved state + transcript.
    _drive(agent, answers=[])

    print("\n" + SEP)
    print("Done. The task was exited and re-entered; it resumed from its own preserved")
    print("state and transcript — never tied to a chat thread.")
    print(SEP)


if __name__ == "__main__":
    main()
