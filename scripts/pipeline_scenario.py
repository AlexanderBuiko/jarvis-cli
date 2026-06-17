"""
Pipeline scenario — the autonomous task FSM in action (`task run`).

Shows the orchestrator rolling the finite state machine forward through stages
on its own (task_autonomy=auto, the default) and stopping only at real gates:
clarification questions and validation. The user never confirms a forward
transition — they only answer when the pipeline asks.

Flow:
    task new
    task run     -> clarification asks what it needs            (gate)
    <answer>
    task run     -> planning -> execution roll forward to a gate
    <answer>
    task run     -> validation -> done                          (rolls to the end)

Usage:
    python scripts/pipeline_scenario.py

Requires OPENROUTER_API_KEY (real LLM calls, like task_scenario.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.config.manager import ConfigManager
from jarvis.openrouter.client import OpenRouterClient
from jarvis.agent import JarvisAgent

SEP = "─" * 66


def chat(agent: JarvisAgent, text: str) -> None:
    print(f"\n[{agent.thread_name}] You: {text}")
    print(f"Jarvis: {agent.chat(text)}")


def task_run(agent: JarvisAgent) -> None:
    print(f"\n[{agent.thread_name}] ! task run")
    for r in agent.run_task():
        if r.blocked:
            print(f"  [{r.stage}] blocked: {r.blocked}")
            continue
        arrow = f" → {r.advanced_to}" if r.advanced_to else ""
        print(f"  [{r.stage}]{arrow}")
        print(f"    {r.text}")
    t = agent.active_task
    print(f"  (stage now: {t['stage']}, expected: {t['expected_action'] or '—'})")


def main() -> None:
    try:
        config = ConfigManager()
        client = OpenRouterClient()
    except EnvironmentError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        sys.exit(1)

    config.set("seed", "42")  # reproducibility
    # task_autonomy defaults to "auto"; set explicitly to make the demo obvious.
    config.set("task_autonomy", "auto")
    agent = JarvisAgent(client, config)

    agent.new_thread("pipeline-demo")
    task = agent.create_task("packing_list")
    print(SEP)
    print(f"Thread = '{agent.thread_name}'   Task = {task['name']} ({task['id']})")
    print("task_autonomy = auto  (forward stages roll on their own)")
    print(SEP)

    # 1) First run: clarification should stop and ask what it needs.
    task_run(agent)

    # 2) Answer, then run again — planning and execution roll forward automatically.
    chat(
        agent,
        "Make me a 3-item packing list for a weekend hiking trip. Keep the plan to "
        "3 bullet points. In execution just produce the 3 items. Validation = the "
        "list has exactly 3 hiking-appropriate items.",
    )
    task_run(agent)

    # 3) Provide any execution input it asked for, then finish the pipeline.
    chat(agent, "Looks good, go ahead and finalise it.")
    task_run(agent)

    print("\n" + SEP)
    print("Done. The pipeline advanced through the stages by itself; the only manual")
    print("inputs were answers at the clarification/execution gates — never a forward")
    print("transition. Every advance still went through the code-enforced FSM.")
    print(SEP)


if __name__ == "__main__":
    main()
