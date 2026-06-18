"""
Task scenario — a short, end-to-end demo of working-memory tasks.

Drives a single task through its whole lifecycle and, crucially, FINISHES IT ON
A DIFFERENT THREAD than it started on — showing that task state (the approved
plan and each stage's result) is shared across chats while the conversation
history is not.

Flow:
    Thread A  (learn-spanish-A)
      task new            -> clarification
      <detailed 1st turn> -> agent restates understanding
      task next           -> planning   (short plan)
      task next           -> execution  (present the phrases)
      <"got it">
      task next           -> validation (simple quiz)
      <answers>
    Thread B  (learn-spanish-B)   ← brand-new chat, empty history
      task start          -> re-attach the SAME task
      <"remind me where we are"> -> agent answers from shared task state
      task next           -> done

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

    # ── Thread A: start the task and drive it into execution ─────────────────
    agent.new_thread("learn-spanish-A")
    task = agent.create_task("spanish_phrases")
    print(SEP)
    print(f"Thread A = '{agent.thread_name}'   Task = {task['name']} ({task['id']})")
    print(SEP)

    _drive(
        agent,
        answers=[
            "Help me memorise exactly 3 Spanish travel phrases: 'hello', 'thank you', "
            "and 'where is the bathroom?'. Plan = 3 numbered steps, one phrase each. "
            "Execution shows each phrase with its translation. Done when I can recall all three.",
        ],
        stop_at_stage="validation",   # pause before finishing, to switch threads
    )

    # ── Thread B: a brand-new chat — no shared history ───────────────────────
    agent.pause_task()
    agent.new_thread("learn-spanish-B")
    print("\n" + SEP)
    print(f"Switched to Thread B = '{agent.thread_name}'  (empty history)")
    print(SEP)

    agent.start_task("spanish_phrases")
    print(f"! task start spanish_phrases   → stage '{agent.active_task['stage']}' re-attached")

    # The only thing the agent knows here is the shared TASK state (plan + stage
    # results), injected via the working-memory block — this thread has no chat
    # history of the earlier turns. Driving from validation finishes the task.
    _drive(agent, answers=[])

    print("\n" + SEP)
    print("Done. The task started on Thread A and finished on Thread B; the agent on")
    print("Thread B recalled the plan and progress purely from shared task state.")
    print(SEP)


if __name__ == "__main__":
    main()
