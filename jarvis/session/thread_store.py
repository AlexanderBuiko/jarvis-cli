"""
Thread-based conversation persistence.

Each thread is a JSON file under ~/.jarvis/threads/<id>.json:
  {
    "id":         "a1b2c3d4",
    "name":       "japan",
    "created_at": "2026-06-09T14:00:00",
    "messages":   [{"role": "…", "content": "…"}, …]
  }

The most recently written file is treated as the last active thread.
Legacy single-file history (~/.jarvis/history.json) is migrated on first use.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_THREADS_DIR = Path.home() / ".jarvis" / "threads"
_LEGACY_FILE = Path.home() / ".jarvis" / "history.json"


class ThreadStore:
    def __init__(self, directory: Path = _THREADS_DIR) -> None:
        self._dir = directory

    # ── Migration ──────────────────────────────────────────────────────────────

    def migrate_legacy(self) -> None:
        """Import ~/.jarvis/history.json as a thread named 'restored', then delete it."""
        if not _LEGACY_FILE.exists():
            return
        try:
            data = json.loads(_LEGACY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = []
        thread_id = uuid4().hex[:8]
        self._write(thread_id, "restored", data)
        _LEGACY_FILE.unlink(missing_ok=True)

    # ── Core operations ────────────────────────────────────────────────────────

    def new_thread(self, name: str | None = None) -> tuple[str, str]:
        """Create an empty thread. Returns (id, name)."""
        thread_id = uuid4().hex[:8]
        thread_name = name or thread_id
        self._write(thread_id, thread_name, [])
        return thread_id, thread_name

    def save(self, thread_id: str, name: str, messages: list[dict]) -> None:
        self._write(thread_id, name, messages)

    def load_last(self) -> tuple[str, str, list[dict]] | None:
        """Return (id, name, messages) for the most recently modified thread, or None."""
        files = self._all_files()
        if not files:
            return None
        latest = max(files, key=lambda p: p.stat().st_mtime)
        return self._read(latest)

    def load_by_name_or_id(self, query: str) -> tuple[str, str, list[dict]] | None:
        """Find a thread by exact name match, then by id prefix. Returns None if not found."""
        candidates = []
        for path in self._all_files():
            result = self._read(path)
            if result is None:
                continue
            tid, tname, messages = result
            if tname == query:
                return tid, tname, messages
            if tid.startswith(query):
                candidates.append((tid, tname, messages, path.stat().st_mtime))
        if len(candidates) == 1:
            tid, tname, messages, _ = candidates[0]
            return tid, tname, messages
        return None

    def rename(self, thread_id: str, new_name: str, messages: list[dict]) -> None:
        self._write(thread_id, new_name, messages)

    def delete(self, thread_id: str) -> bool:
        """Delete the thread file. Returns True if the file existed."""
        path = self._path(thread_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(self) -> list[dict]:
        """Return thread metadata sorted by modification time, newest first."""
        results = []
        for path in self._all_files():
            result = self._read(path)
            if result is None:
                continue
            tid, tname, messages = result
            results.append({
                "id": tid,
                "name": tname,
                "turns": len(messages) // 2,
                "mtime": path.stat().st_mtime,
            })
        results.sort(key=lambda r: r["mtime"], reverse=True)
        return results

    # ── Internal ───────────────────────────────────────────────────────────────

    def _path(self, thread_id: str) -> Path:
        return self._dir / f"{thread_id}.json"

    def _all_files(self) -> list[Path]:
        if not self._dir.exists():
            return []
        return list(self._dir.glob("*.json"))

    def _write(self, thread_id: str, name: str, messages: list[dict]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(thread_id)
        payload: dict = {"id": thread_id, "name": name, "messages": messages}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                payload["created_at"] = existing.get("created_at", _now())
            except (json.JSONDecodeError, OSError):
                payload["created_at"] = _now()
        else:
            payload["created_at"] = _now()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read(self, path: Path) -> tuple[str, str, list[dict]] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        tid = data.get("id") or path.stem
        tname = data.get("name") or tid
        messages = data.get("messages") or []
        if not isinstance(messages, list):
            messages = []
        return tid, tname, messages


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
