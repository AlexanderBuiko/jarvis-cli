"""Tests for the mutating-tool permission gate (jarvis/mcp/permissions.py).

Writes that aren't pre-authorised are not denied outright — they're queued in
``pending`` for the REPL to approve after the turn.
"""

from jarvis.mcp.permissions import ToolPermissions


def _write(dry_run=False, path="x.md"):
    return "files__write_file", {"path": path, "content": "hi", "dry_run": dry_run}


def test_readonly_tools_bypass_the_gate():
    gate = ToolPermissions()
    assert gate.allow("files__read_file", {"path": "x"}) is True
    assert gate.allow("files__search_files", {"query": "x"}) is True
    assert gate.pending == []


def test_dry_run_write_bypasses_the_gate():
    gate = ToolPermissions()
    name, args = _write(dry_run=True)
    assert gate.allow(name, args) is True
    assert gate.pending == []


def test_auto_allows_writes_in_turn():
    gate = ToolPermissions(auto=True)
    name, args = _write()
    assert gate.allow(name, args) is True
    assert gate.pending == []                 # ran in-turn, nothing queued


def test_auto_can_be_a_live_predicate():
    state = {"on": False}
    gate = ToolPermissions(auto=lambda: state["on"])
    name, args = _write()
    assert gate.allow(name, args) is False    # queued while off
    state["on"] = True
    assert gate.allow(name, args) is True     # runs in-turn once on


def test_unauthorised_write_is_queued_not_run():
    gate = ToolPermissions()
    name, args = _write()
    assert gate.allow(name, args) is False    # not run now
    assert len(gate.pending) == 1
    assert gate.pending[0]["args"]["path"] == "x.md"


def test_take_pending_returns_and_clears():
    gate = ToolPermissions()
    name, args = _write()
    gate.allow(name, args)
    assert len(gate.take_pending()) == 1
    assert gate.pending == []                 # drained


def test_grant_always_lets_later_writes_run():
    gate = ToolPermissions()
    name, args = _write()
    assert gate.allow(name, args) is False    # first is queued
    gate.grant_always(name)                   # user chose "allow all"
    assert gate.allow(*_write(path="y.md")) is True
    assert gate.pending == [gate.pending[0]]  # only the first queued (y.md ran in-turn)


def test_pending_is_deduped_per_path_latest_wins():
    gate = ToolPermissions()
    gate.allow("files__write_file", {"path": "a.md", "content": "v1"})
    gate.allow("files__write_file", {"path": "a.md", "content": "v2"})
    assert len(gate.pending) == 1
    assert gate.pending[0]["args"]["content"] == "v2"


def test_dotted_tool_name_is_matched():
    gate = ToolPermissions()
    assert gate.allow("files.write_file", {"path": "x", "content": "y"}) is False
    assert len(gate.pending) == 1


def test_previews_are_recorded_and_taken():
    gate = ToolPermissions()
    gate.add_preview("x.md", "[dry run — would create]\n+hi")
    assert len(gate.previews) == 1
    taken = gate.take_previews()
    assert taken[0]["path"] == "x.md"
    assert gate.previews == []          # drained


def test_delete_file_is_also_gated():
    gate = ToolPermissions()
    assert gate.allow("files__delete_file", {"path": "x.md"}) is False   # queued
    assert gate.pending[0]["args"]["path"] == "x.md"
    # a dry-run delete preview bypasses the gate
    gate2 = ToolPermissions()
    assert gate2.allow("files__delete_file", {"path": "x.md", "dry_run": True}) is True
