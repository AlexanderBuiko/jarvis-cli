"""
Local project-files MCP server — lets the assistant read, search, and edit the
developer's working tree over MCP (stdio).

Like the ``git`` server (:mod:`jarvis.mcp_servers.git_server`), this MUST run locally: a
remote/Cloud Run process can't touch the developer's files. Registered in
``servers.json`` under the name ``files``, so its tools are namespaced ``files.<tool>``
and the agent's tool-calling loop can pick them to satisfy a goal-level instruction
("find every use of X", "write an ADR") — the assistant initiates the file work itself.

Everything is confined to a **root** directory (``JARVIS_FILES_ROOT`` if set, else the
process cwd — where the developer launched the CLI). A path that escapes the root is
refused; this is the safety boundary. Noise (``.git``, ``__pycache__``, virtualenvs,
``node_modules``) and binary/oversized files are skipped.

Writes never *delete* — only create/modify. ``write_file(dry_run=True)`` returns a diff
without touching disk (the safe "prepare a diff" path); the write itself is gated on the
CLI side by the tool-permission policy (:mod:`jarvis.mcp.permissions`).

Run standalone (e.g. for the MCP Inspector):

    python -m jarvis.mcp_servers.files_server        # serves over stdio
"""

from __future__ import annotations

import difflib
import fnmatch
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("files")

# In-memory edit journal for this server process (≈ the CLI session). Each real
# write_file pushes a snapshot of the file's prior state, so revert_file can restore
# *exactly* what the assistant changed (undo a create by deleting, a modify by
# restoring the old text) — precisely, without git's "revert to last commit" imprecision.
# LIFO per path: reverting undoes the most recent write to that file.
_journal: list[dict] = []


def clear_journal() -> None:
    """Empty the edit journal (used by tests; harmless otherwise)."""
    _journal.clear()


def _record(rel: str, before: str, before_existed: bool, after: str | None, op: str) -> None:
    _journal.append(
        {"path": rel, "before": before, "before_existed": before_existed,
         "after": after, "op": op}
    )

# Directories never worth reading/searching/listing — VCS internals, caches, deps.
_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache",
              ".pytest_cache", ".ruff_cache", ".idea", "dist", "build", ".tox"}
# A file bigger than this is treated as not-text for reading/searching.
_MAX_SCAN_BYTES = 1_000_000


def _root() -> str:
    """The project root to operate under: ``JARVIS_FILES_ROOT`` env, else the cwd."""
    return os.path.realpath(os.environ.get("JARVIS_FILES_ROOT", "").strip() or os.getcwd())


def _resolve(path: str) -> str:
    """Resolve ``path`` (repo-relative or absolute) to a realpath **inside the root**.

    Raises ``ValueError`` if it escapes the root — the confinement boundary.
    """
    root = _root()
    candidate = path if os.path.isabs(path) else os.path.join(root, path)
    resolved = os.path.realpath(candidate)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError(f"path '{path}' is outside the project root")
    return resolved


def _rel(abspath: str) -> str:
    """Root-relative display path (posix-style)."""
    return os.path.relpath(abspath, _root()).replace(os.sep, "/")


def _skip(abspath: str) -> bool:
    """True if any path segment (below the root) is a skipped directory."""
    rel = os.path.relpath(abspath, _root())
    return any(part in _SKIP_DIRS for part in rel.split(os.sep))


def _match(rel: str, glob: str) -> bool:
    """Match a root-relative posix path against a glob.

    fnmatch's ``*`` spans ``/``, so ``jarvis/*`` and ``**/*.py`` match nested paths.
    fnmatch has no real ``**``, though, and a leading ``**/`` otherwise *requires* a
    slash — so top-level files miss ``**/*``. Treat ``**/`` as "zero or more dirs" by
    also trying the pattern with the first ``**/`` removed.
    """
    if fnmatch.fnmatch(rel, glob):
        return True
    if "**/" in glob:
        return fnmatch.fnmatch(rel, glob.replace("**/", "", 1))
    return False


def _iter_files(glob: str):
    """Yield abspaths of files under the root matching ``glob`` (posix relpath), skipping
    noise dirs. ``glob`` is matched against the root-relative path (e.g. ``jarvis/**/*.py``
    or ``**/*``)."""
    root = _root()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            abspath = os.path.join(dirpath, name)
            rel = os.path.relpath(abspath, root).replace(os.sep, "/")
            if _match(rel, glob):
                yield abspath


def _read_text(abspath: str) -> str | None:
    """Return file text, or ``None`` if it's too big or not decodable as UTF-8 (binary)."""
    try:
        if os.path.getsize(abspath) > _MAX_SCAN_BYTES:
            return None
        with open(abspath, encoding="utf-8") as handle:
            return handle.read()
    except (UnicodeDecodeError, OSError):
        return None


@mcp.tool()
def list_files(glob: str = "**/*", limit: int = 200) -> str:
    """List project files (root-relative paths) matching a glob, skipping VCS/cache/dep dirs.

    Use this to discover what exists before reading or editing. ``glob`` matches the
    root-relative path (e.g. ``**/*.py``, ``jarvis/mcp_servers/*``). At most ``limit``
    paths are returned (a truncation note is appended if there are more).
    """
    try:
        matches = sorted(_rel(p) for p in _iter_files(glob))
    except Exception as exc:  # noqa: BLE001 — report, don't crash the tool call
        return f"error: {exc}"
    if not matches:
        return f"(no files match '{glob}')"
    shown = matches[:limit]
    out = "\n".join(shown)
    if len(matches) > limit:
        out += f"\n… {len(matches) - limit} more (raise limit or narrow the glob)"
    return out


@mcp.tool()
def read_file(path: str, max_bytes: int = 40000) -> str:
    """Return the text content of a project file.

    ``path`` is root-relative (or absolute inside the root). Output is truncated to
    ``max_bytes`` with a note if the file is larger. Binary/undecodable files are
    reported rather than dumped. Paths outside the project root are refused.
    """
    try:
        abspath = _resolve(path)
    except ValueError as exc:
        return f"error: {exc}"
    if not os.path.isfile(abspath):
        return f"error: no such file '{path}'"
    text = _read_text(abspath)
    if text is None:
        return f"error: '{path}' is not a readable text file (binary or too large)"
    if len(text) > max_bytes:
        return text[:max_bytes] + f"\n… [truncated at {max_bytes} bytes; file is {len(text)} bytes]"
    return text


@mcp.tool()
def search_files(query: str, glob: str = "**/*", regex: bool = False, limit: int = 200) -> str:
    """Search for ``query`` across many project files; return ``path:line: text`` matches.

    The primitive for "find every place X is used" / "search info in multiple files".
    ``query`` is a plain substring by default, or a Python regular expression when
    ``regex=True``. ``glob`` narrows the files scanned (e.g. ``**/*.py``). At most
    ``limit`` matching lines are returned.
    """
    if not (query or "").strip():
        return "error: query must be non-empty"
    matcher = None
    if regex:
        import re
        try:
            matcher = re.compile(query)
        except re.error as exc:
            return f"error: bad regex: {exc}"
    hits: list[str] = []
    try:
        for abspath in _iter_files(glob):
            text = _read_text(abspath)
            if text is None:
                continue
            rel = _rel(abspath)
            for lineno, line in enumerate(text.splitlines(), 1):
                found = matcher.search(line) if matcher else (query in line)
                if found:
                    hits.append(f"{rel}:{lineno}: {line.strip()}")
                    if len(hits) >= limit:
                        return "\n".join(hits) + f"\n… (stopped at {limit} matches)"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
    if not hits:
        return f"(no matches for '{query}' in '{glob}')"
    return "\n".join(hits)


def _unified_diff(old: str, new: str, rel: str) -> str:
    """Unified diff old→new for display, labelled with the repo-relative path."""
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
    )
    text = "".join(diff)
    return text if text.strip() else "(no changes)"


@mcp.tool()
def write_file(path: str, content: str, dry_run: bool = False) -> str:
    """Create or modify a project file, returning the unified diff of the change.

    Computes the diff between the current content (empty if the file is new) and
    ``content``. With ``dry_run=True`` **nothing is written** — the diff is returned so a
    change can be previewed / listed safely. With ``dry_run=False`` the file is written
    (parent directories are created) and the applied diff is returned. This tool never
    deletes. Paths outside the project root are refused.
    """
    try:
        abspath = _resolve(path)
    except ValueError as exc:
        return f"error: {exc}"
    if os.path.isdir(abspath):
        return f"error: '{path}' is a directory"
    existed_before = os.path.isfile(abspath)
    old = ""
    if existed_before:
        existing = _read_text(abspath)
        if existing is None:
            return f"error: '{path}' exists but isn't editable text (binary or too large)"
        old = existing
    rel = _rel(abspath)
    diff = _unified_diff(old, content, rel)
    if old == content:
        return f"(no changes — '{rel}' already has this content)"
    verb = "created" if not existed_before else "updated"
    if dry_run:
        return f"[dry run — would {'create' if not existed_before else 'update'}]\n{diff}"
    try:
        os.makedirs(os.path.dirname(abspath) or ".", exist_ok=True)
        with open(abspath, "w", encoding="utf-8") as handle:
            handle.write(content)
    except OSError as exc:
        return f"error: could not write '{path}': {exc}"
    _record(rel, before=old, before_existed=existed_before, after=content, op=verb)
    return f"[{verb} '{rel}']\n{diff}  (revert with: revert_file path={rel})"


@mcp.tool()
def delete_file(path: str, dry_run: bool = False) -> str:
    """Delete a project file, returning the diff of what is removed.

    ``dry_run=True`` returns the removal diff **without deleting** (a safe preview);
    ``dry_run=False`` removes the file. The deletion is journaled, so ``revert_file``
    (or ``revert_last``) restores the file with its exact prior content — deletion is
    undoable within the session. Refuses directories and paths outside the project root.
    """
    try:
        abspath = _resolve(path)
    except ValueError as exc:
        return f"error: {exc}"
    if os.path.isdir(abspath):
        return f"error: '{path}' is a directory (only files can be deleted)"
    if not os.path.isfile(abspath):
        return f"error: no such file '{path}'"
    old = _read_text(abspath)
    if old is None:
        return f"error: '{path}' isn't a readable text file (binary or too large); refusing to delete"
    rel = _rel(abspath)
    diff = _unified_diff(old, "", rel)
    if dry_run:
        return f"[dry run — would delete]\n{diff}"
    try:
        os.remove(abspath)
    except OSError as exc:
        return f"error: could not delete '{path}': {exc}"
    # Journal the removal so it can be reverted (before_existed=True → revert re-writes
    # the content; after=None marks the post-op absence for the hand-edit guard).
    _record(rel, before=old, before_existed=True, after=None, op="deleted")
    return f"[deleted '{rel}']\n{diff}  (revert with: revert_file path={rel})"


@mcp.tool()
def list_changes() -> str:
    """List the file writes made this session, oldest first — the revert history.

    Each line is ``N. created|modified <path>``. Revert the most recent write to a file
    with ``revert_file``, or the single most recent write overall with ``revert_last``.
    """
    if not _journal:
        return "(no file changes recorded this session)"
    lines = []
    for i, entry in enumerate(_journal, 1):
        verb = entry.get("op") or ("modified" if entry["before_existed"] else "created")
        lines.append(f"{i}. {verb} {entry['path']}")
    return "\n".join(lines)


def _do_revert(entry: dict, force: bool) -> str:
    """Undo one journal entry: restore prior text, or delete a file it created."""
    rel = entry["path"]
    try:
        abspath = _resolve(rel)
    except ValueError as exc:
        return f"error: {exc}"
    # Guard against clobbering edits made *after* the assistant wrote the file: if the
    # current content isn't what the assistant last wrote, only proceed with force.
    current = _read_text(abspath) if os.path.isfile(abspath) else None
    if not force and current != entry["after"]:
        return (f"'{rel}' has changed since the assistant wrote it — reverting would "
                f"discard those later edits. Re-run with force=true to override.")
    if entry["before_existed"]:
        try:
            with open(abspath, "w", encoding="utf-8") as handle:
                handle.write(entry["before"])
        except OSError as exc:
            return f"error: could not restore '{rel}': {exc}"
        diff = _unified_diff(current or "", entry["before"], rel)
        result = f"[reverted '{rel}' to its prior content]\n{diff}"
    else:
        # The assistant created this file — undo means remove it.
        try:
            if os.path.isfile(abspath):
                os.remove(abspath)
        except OSError as exc:
            return f"error: could not remove '{rel}': {exc}"
        result = f"[reverted '{rel}' — removed the file the assistant created]"
    _journal.remove(entry)
    return result


@mcp.tool()
def revert_file(path: str, force: bool = False) -> str:
    """Undo the most recent write the assistant made to ``path`` this session.

    Restores the file's content from just before that write (a file the assistant
    *created* is deleted; a *modified* file is restored to its prior text) and drops that
    entry from the history — so calling again steps further back through earlier writes to
    the same file. If you've hand-edited the file since the assistant wrote it, the revert
    is refused unless ``force=True`` (so your later edits aren't silently discarded).
    """
    for entry in reversed(_journal):
        if entry["path"] == path.replace(os.sep, "/"):
            return _do_revert(entry, force)
    return f"(no recorded change to '{path}' to revert)"


@mcp.tool()
def revert_last(force: bool = False) -> str:
    """Undo the single most recent write the assistant made this session (any file).

    Same restore/guard rules as ``revert_file``; ``force=True`` overrides the "changed
    since" guard.
    """
    if not _journal:
        return "(no file changes recorded this session)"
    return _do_revert(_journal[-1], force)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
