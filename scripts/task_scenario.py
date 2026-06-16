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

SEP = "─" * 66


def _stage(agent: JarvisAgent) -> str:
    t = agent.active_task
    return t["stage"] if t else "—"


def chat(agent: JarvisAgent, text: str) -> None:
    print(f"\n[{agent.thread_name} · {_stage(agent)}] You: {text}")
    print(f"Jarvis: {agent.chat(text)}")


def task_next(agent: JarvisAgent) -> None:
    print(f"\n[{agent.thread_name}] ! task next")
    new_stage, reply = agent.next_stage()
    if new_stage is None:
        print(reply)
        return
    print(f"→ now in '{new_stage}'\nJarvis: {reply}")


def main() -> None:
    try:
        config = ConfigManager()
        client = OpenRouterClient()
    except EnvironmentError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(1)

    config.set("seed", "42")  # reproducibility
    agent = JarvisAgent(client, config)

    # ── Thread A: start and run the task up to validation ────────────────────
    agent.new_thread("learn-spanish-A")
    task = agent.create_task("spanish_phrases")
    print(SEP)
    print(f"Thread A = '{agent.thread_name}'   Task = {task['name']} ({task['id']})")
    print(SEP)

    # Detailed initial turn so clarification can finish in one go.
    chat(
        agent,
        "Help me memorise exactly 3 Spanish travel phrases: 'hello', 'thank you', "
        "and 'where is the bathroom?'. Plan should be short. In execution, just show "
        "me the three phrases with translations. Validation = I correctly recall all "
        "three when you quiz me.",
    )

    task_next(agent)              # clarification -> planning  (short plan)
    task_next(agent)              # planning -> execution      (present phrases)
    chat(agent, "Got it, I've read them.")
    task_next(agent)             # execution -> validation     (quiz)
    chat(agent, "Hola; Gracias; ¿Dónde está el baño?")

    # ── Thread B: a brand-new chat — no shared history ───────────────────────
    agent.new_thread("learn-spanish-B")
    print("\n" + SEP)
    print(f"Switched to Thread B = '{agent.thread_name}'  (empty history)")
    print(SEP)

    agent.start_task("spanish_phrases")
    print(f"! task start spanish_phrases   → stage '{_stage(agent)}' re-attached")

    # The only thing the agent knows here is the shared TASK state (plan + stage
    # results), injected via the working-memory block — this thread has no chat
    # history of the earlier turns.
    chat(agent, "Remind me what I'm working on and what's left to do.")

    task_next(agent)             # validation -> done, on a different thread

    print("\n" + SEP)
    print("Done. The task started on Thread A and finished on Thread B; the agent on")
    print("Thread B recalled the plan and progress purely from shared task state.")
    print(SEP)


if __name__ == "__main__":
    main()
