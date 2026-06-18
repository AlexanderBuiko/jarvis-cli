"""
Working-memory task persistence.

A task is the state of a piece of work that may span one or several threads.
It lives independently of any thread as a JSON file under ~/.jarvis/tasks/<id>.json:
  {
    "id":            "a1b2c3d4",
    "name":          "Prepare Android interview",
    "stage":         "execution",
    "current_step":  "…",          # the step being worked within the current stage
    "expected_action": "…",        # machine-readable next action (e.g. await_user, run:task next)
    "plan_steps":    ["…", …],     # the plan parsed into ordered, trackable steps
    "step_index":    2,            # index of the in-progress step (steps before it are done)
    "description":   "…",
    "plan":          "…",
    "completed":     ["…", …],
    "remaining":     ["…", …],
    "notes":         "…",
    "stage_outputs": {"clarification": "…", "planning": "…"},
    "thread_ids":    ["abcd1234", …],
    "created_at":    "2026-06-16T14:00:00",
    "updated_at":    "2026-06-16T14:30:00"
  }

A thread references its active task via the "active_task_id" field in the thread
file (see ThreadStore). The task file is the single source of truth for task state.

Stage transitions are enforced here in code (not in prompts) so that the rules
survive summarisation and compaction.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_TASKS_DIR = Path.home() / ".jarvis" / "tasks"

# Task state machine. Basic stages; expand with caution.
STAGES: tuple[str, ...] = ("clarification", "planning", "execution", "validation", "done")

# Allowed forward (and revision) transitions. Anything not listed is rejected.
# The first entry of each list is the default forward transition; later entries
# are revision/branch targets that must be requested explicitly.
ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "clarification": ["planning"],
    "planning":      ["execution"],
    "execution":     ["validation", "planning"],  # validate, or back to planning to revise the plan
    "validation":    ["done", "execution"],        # done, or back to execution for revision
    "done":          [],
}


class TaskStore:
    def __init__(self, directory: Path = _TASKS_DIR) -> None:
        self._dir = directory

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
            "step_index": 0,
            "description": "",
            "plan": "",
            "completed": [],
            "remaining": [],
            "notes": "",
            "stage_outputs": {},
            "thread_ids": [],
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

    def advance_stage(self, task: dict, target: str | None = None) -> str:
        """Move the task to the next stage, enforcing ALLOWED_TRANSITIONS in code.

        target is required only to disambiguate the validation stage (done vs
        execution); for every other stage the single allowed transition is used.
        Raises ValueError if the transition is not permitted.
        """
        current = task["stage"]
        allowed = ALLOWED_TRANSITIONS.get(current, [])
        if not allowed:
            raise ValueError(f"task is already in the terminal stage '{current}'")
        if target is None:
            target = allowed[0]
        if target not in allowed:
            raise ValueError(
                f"cannot move {current} → {target} "
                f"(allowed: {', '.join(allowed)})"
            )
        task["stage"] = target
        # current_step belongs to a stage; clear it so the new stage starts fresh.
        task["current_step"] = ""
        # Entering execution (forward, or back from validation for rework) starts
        # step-wise progress from the first plan step.
        if target == "execution":
            task["step_index"] = 0
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
        data.setdefault("step_index", 0)
        data.setdefault("description", "")
        data.setdefault("plan", "")
        data.setdefault("completed", [])
        data.setdefault("remaining", [])
        data.setdefault("notes", "")
        data.setdefault("stage_outputs", {})
        data.setdefault("thread_ids", [])
        return data


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
