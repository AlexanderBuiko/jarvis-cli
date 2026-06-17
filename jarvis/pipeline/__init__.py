"""
The task pipeline: a managed process built from abstractions.

  invariants.py   — InvariantChecker (the natural-language "requirements linter")
  base.py         — StageAgent contract + StageResult + control-marker grammar
  stages.py       — the per-stage agents (clarification → planning → execution → validation)
  orchestrator.py — drives the finite state machine across stage-agents
"""
