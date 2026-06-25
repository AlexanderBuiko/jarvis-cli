"""
Auto-load configuration from ``.env`` files — the way git reads ``~/.gitconfig``
and ``.git/config`` on its own, so you never re-export secrets each run.

Precedence (highest wins):

  1. the real environment    — an inline ``FOO=… jarvis`` or prior ``export``
                               always wins (handy for one-off overrides).
  2. project-local ``./.env`` — like ``.git/config``: per-checkout settings.
  3. global ``~/.jarvis/.env`` — like ``~/.gitconfig``: machine-wide defaults.

Only keys not already present are filled (``os.environ.setdefault``), so the
order above holds and nothing you set explicitly is ever clobbered. Local is
read before global, so local overrides global while both defer to the real
environment.

Format: ``KEY=value`` per line. Blank lines and ``#`` comments are ignored; an
optional leading ``export`` is allowed; surrounding single/double quotes are
stripped. This is a generic env file, not a fixed schema — any key is loaded
(e.g. OPENROUTER_API_KEY, JARVIS_MCP_URL, MCP_API_KEY).
"""

from __future__ import annotations

import os
from pathlib import Path

GLOBAL_ENV = Path.home() / ".jarvis" / ".env"
LOCAL_ENV = Path(".env")


def _parse(path: Path) -> list[tuple[str, str]]:
    """Parse a .env file into (key, value) pairs. Missing/unreadable → []."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    pairs: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key:
            pairs.append((key, val))
    return pairs


def load_env_files(*, local: Path = LOCAL_ENV, global_: Path = GLOBAL_ENV) -> list[str]:
    """Load local then global .env into os.environ without overriding real env.

    Idempotent and safe to call more than once. Returns the paths actually
    applied (those that existed and held at least one key), for status display.
    """
    applied: list[str] = []
    for path in (local, global_):  # local first → local wins over global
        pairs = _parse(path)
        if not pairs:
            continue
        for key, val in pairs:
            os.environ.setdefault(key, val)
        applied.append(str(path))
    return applied
