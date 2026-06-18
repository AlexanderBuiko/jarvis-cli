"""
Behaviour log — a compact, global record of how the user interacts with Jarvis.

Stored separately from chat threads (one line per turn in ~/.jarvis/behavior.jsonl)
and shared across all threads. It is intentionally minimal: it captures signals
about the user's *preferences* (how long the answers are, which strategies they
favour, whether they work in tasks), NOT the conversation content itself.

This log is the input to the profile refiner (`profile` command), which uses it
to propose updates to the Style section of the long-term profile.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

# Keep the log bounded: only the most recent interactions inform personalisation,
# so the file is trimmed to this many lines on write. Older records are dropped.
_MAX_RECORDS = 50


class BehaviorLog:
    def __init__(self, path: Path | None = None, max_records: int = _MAX_RECORDS) -> None:
        # Resolve home at instantiation (not import) so $HOME-based test isolation works.
        self._path = path or (Path.home() / ".jarvis" / "behavior.jsonl")
        self._max_records = max_records

    def record(
        self,
        user_input: str,
        response_chars: int,
        solution_strategy: str,
        context_strategy: str,
        had_task: bool,
    ) -> None:
        """Append a single compact interaction record."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "user_input": user_input,
            "user_chars": len(user_input),
            "response_chars": response_chars,
            "solution_strategy": solution_strategy,
            "context_strategy": context_strategy,
            "had_task": had_task,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._trim()

    def _trim(self) -> None:
        """Keep only the most recent _max_records lines on disk."""
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) > self._max_records:
            kept = lines[-self._max_records:]
            self._path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    def count(self) -> int:
        """Total number of interactions recorded (across all sessions)."""
        if not self._path.exists():
            return 0
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:
            return 0

    def recent(self, n: int) -> list[dict]:
        """Return the most recent up-to-n records, oldest-first."""
        if not self._path.exists():
            return []
        try:
            lines = [ln for ln in self._path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except OSError:
            return []
        records: list[dict] = []
        for line in lines[-n:]:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
