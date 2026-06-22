"""
Working-memory task persistence.

A task is a standalone workspace — a piece of work with its own conversation,
fully independent of chat threads. It lives as a JSON file under
~/.jarvis/tasks/<id>.json:
  {
    "id":            "a1b2c3d4",
    "name":          "Prepare Android interview",
    "stage":         "execution",
    "current_step":  "…",          # the step being worked within the current stage
    "expected_action": "…",        # machine-readable next action (e.g. await_user, await_plan_approval)
    "plan_steps":    ["…", …],     # the plan parsed into ordered, trackable steps
    "plan_deps":     [[], [0], …], # per-step dependencies (0-based) for parallel execution
    "step_index":    2,            # index of the in-progress step (steps before it are done)
    "description":   "…",
    "plan":          "…",
    "notes":         "…",
    "stage_outputs": {"clarification": "…", "planning": "…"},
    "messages":      [{"role": "…", "content": "…"}, …],  # the task's own transcript
    "result_path":   "…",          # file holding the final deliverable, set at done
    "created_at":    "2026-06-16T14:00:00",
    "updated_at":    "2026-06-16T14:30:00"
  }

The task file is the single source of truth for task state. Tasks are entered with
`task start`/`task new` and left with `task exit`; chat threads never reference them.

Stage transitions are enforced here in code (not in prompts) so that the rules
survive summarisation and compaction.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# The FSM policy (valid states + permitted transitions) lives in pipeline.fsm as
# the single source of truth. Re-exported here for backward compatibility with
# callers/tests that import these names from the store.
from ..pipeline.fsm import STAGES, ALLOWED_TRANSITIONS, resolve_transition


class TaskStore:
    def __init__(self, directory: Path | None = None) -> None:
        # Resolve home at instantiation (not import) so $HOME-based test isolation works.
        self._dir = directory or (Path.home() / ".jarvis" / "tasks")

    # ── Core operations ────────────────────────────────────────────────────────

    def new_task(self, name: str | None = None) -> dict:
        """Create a task in the clarification stage. Returns the task dict."""
        task_id = uuid4().hex[:8]
        now = _now()
        task: dict = {
            "id": task_id,
            "name": name or task_id,
            "stage": "clarification",
            "current_step": "",
            "expected_action": "",
            "plan_steps": [],
            "plan_deps": [],
            "step_index": 0,
            "result_path": "",
            "description": "",
            "plan": "",
            "notes": "",
            "stage_outputs": {},
            "messages": [],
            # Accounting: LLM spend accumulated across this task's stage turns.
            "api_call_count": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "created_at": now,
            "updated_at": now,
        }
        self.save(task)
        return task

    def save(self, task: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        task["updated_at"] = _now()
        path = self._path(task["id"])
        path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, task_id: str) -> dict | None:
        path = self._path(task_id)
        if not path.exists():
            return None
        return self._read(path)

    def find(self, query: str) -> dict | None:
        """Find a task by exact name match, then by id prefix. Returns None if not found."""
        candidates: list[dict] = []
        for path in self._all_files():
            task = self._read(path)
            if task is None:
                continue
            if task["name"] == query:
                return task
            if task["id"].startswith(query):
                candidates.append(task)
        if len(candidates) == 1:
            return candidates[0]
        return None

    def list_all(self) -> list[dict]:
        """Return all tasks sorted by last-updated time, newest first."""
        tasks = [t for p in self._all_files() if (t := self._read(p)) is not None]
        tasks.sort(key=lambda t: t.get("updated_at", ""), reverse=True)
        return tasks

    def delete(self, task_id: str) -> bool:
        path = self._path(task_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def save_result(self, task: dict, text: str) -> Path:
        """Write the task's final deliverable to the results/ subdirectory and record its path."""
        results_dir = self._dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        path = results_dir / f"{task['id']}.md"
        path.write_text(text, encoding="utf-8")
        task["result_path"] = str(path)
        self.save(task)
        return path

    def advance_stage(self, task: dict, target: str | None = None) -> str:
        """Move the task to the next stage, enforcing ALLOWED_TRANSITIONS in code.

        target is required only to disambiguate the validation stage (done vs
        execution); for every other stage the single allowed transition is used.
        Raises ValueError if the transition is not permitted.
        """
        target = resolve_transition(task["stage"], target)
        task["stage"] = target
        # current_step belongs to a stage; clear it so the new stage starts fresh.
        task["current_step"] = ""
        # Entering execution (forward, or back from validation for rework) starts
        # step-wise progress from the first plan step. The previous execution log is
        # cleared so a rework produces a FRESH deliverable instead of appending to
        # (and compounding) the old one — otherwise validation keeps re-reading stale,
        # ever-growing output and rework can never converge.
        if target == "execution":
            task["step_index"] = 0
            (task.get("stage_outputs") or {}).pop("execution", None)
        self.save(task)
        return target

    # ── Internal ───────────────────────────────────────────────────────────────

    def _path(self, task_id: str) -> Path:
        return self._dir / f"{task_id}.json"

    def _all_files(self) -> list[Path]:
        if not self._dir.exists():
            return []
        return list(self._dir.glob("*.json"))

    def _read(self, path: Path) -> dict | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        # Fill defaults so older files load cleanly.
        data.setdefault("id", path.stem)
        data.setdefault("name", data["id"])
        data.setdefault("stage", "clarification")
        data.setdefault("current_step", "")
        data.setdefault("expected_action", "")
        data.setdefault("plan_steps", [])
        data.setdefault("plan_deps", [])
        data.setdefault("step_index", 0)
        data.setdefault("result_path", "")
        data.setdefault("description", "")
        data.setdefault("plan", "")
        data.setdefault("notes", "")
        data.setdefault("stage_outputs", {})
        data.setdefault("messages", [])
        data.setdefault("api_call_count", 0)
        data.setdefault("total_tokens", 0)
        data.setdefault("total_cost", 0.0)
        return data


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
