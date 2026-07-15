"""
Local git MCP server — exposes the developer's working-tree state over MCP (stdio).

Run as a subprocess by the CLI's MCP client fleet (registered in ``servers.json``
under the name ``git``, so its tools are namespaced ``git.<tool>``). This must be a
**local** server: a remote/Cloud Run process can't read the developer's ``.git``, so
"what branch am I on" is only answerable by something running on the same machine.

Minimum for the assignment: ``get_current_branch``. It reads the repository at
``GIT_REPO_PATH`` if set, else the process working directory (which is where the
developer launched the CLI).

Run standalone (e.g. for the MCP Inspector):

    python -m jarvis.mcp_servers.git_server        # serves over stdio
"""

from __future__ import annotations

import os
import subprocess

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("git")


def _repo_path() -> str:
    """The repository to inspect: ``GIT_REPO_PATH`` env, else the process cwd."""
    return os.environ.get("GIT_REPO_PATH", "").strip() or os.getcwd()


def _git(*args: str) -> str:
    """Run a git command in the repo and return its trimmed stdout.

    Raises ``RuntimeError`` with git's own message on failure (e.g. not a repo).
    """
    proc = subprocess.run(
        ["git", *args],
        cwd=_repo_path(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or "git command failed")
    return proc.stdout.strip()


@mcp.tool()
def get_current_branch() -> str:
    """Return the current git branch of the local working tree.

    Returns the branch name (e.g. ``main``), or ``HEAD`` when detached. On any error
    (not a git repository, git missing) returns a short ``error: …`` line rather than
    raising, so the caller can degrade gracefully.
    """
    try:
        return _git("rev-parse", "--abbrev-ref", "HEAD")
    except Exception as exc:  # noqa: BLE001 — report, don't crash the tool call
        return f"error: {exc}"


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
