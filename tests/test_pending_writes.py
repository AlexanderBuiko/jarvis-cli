"""The REPL drains the gate's queued writes after a turn and applies the approved ones
(jarvis/repl/loop.py::_process_pending_writes)."""

from jarvis.mcp.permissions import ToolPermissions
from jarvis.repl import loop


class _Provider:
    """Fake tool provider: records real applies; dry-run peeks return a preview."""

    def __init__(self):
        self.applied: list[tuple[str, dict]] = []

    def call_tool(self, name, args):
        if args.get("dry_run"):
            return "[dry run — not written]\n+hi"
        self.applied.append((name, args))
        return f"[created '{args['path']}']"


class _Controller:
    """Fake InputController.approve_write returning a scripted sequence of decisions."""

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.seen: list[str] = []

    def approve_write(self, path, diff, action="update", window=10):
        self.seen.append((path, action))
        return self._decisions.pop(0)


def _queued_gate(*paths):
    gate = ToolPermissions()
    for p in paths:
        gate.allow("files__write_file", {"path": p, "content": "hi"})
    return gate


def test_apply_once_writes_and_drains():
    gate = _queued_gate("a.md")
    provider, controller = _Provider(), _Controller(["once"])
    loop._process_pending_writes(gate, provider, controller)
    assert provider.applied == [("files__write_file", {"path": "a.md", "content": "hi"})]
    assert gate.pending == []                              # queue drained


def test_skip_writes_nothing():
    gate = _queued_gate("a.md")
    provider, controller = _Provider(), _Controller(["skip"])
    loop._process_pending_writes(gate, provider, controller)
    assert provider.applied == []
    assert gate.pending == []


def test_apply_does_not_redump_the_whole_diff(capsys):
    # The frame already showed the change; applying prints only a one-line confirmation.
    gate = _queued_gate("a.md")
    provider, controller = _Provider(), _Controller(["once"])
    loop._process_pending_writes(gate, provider, controller)
    out = capsys.readouterr().out
    assert "revert:" in out                                # compact confirmation shown
    assert "+hi" not in out                                # the diff body was NOT re-dumped


def test_allow_all_grants_session_and_applies():
    gate = _queued_gate("a.md")
    provider, controller = _Provider(), _Controller(["always"])
    loop._process_pending_writes(gate, provider, controller)
    assert provider.applied == [("files__write_file", {"path": "a.md", "content": "hi"})]
    # subsequent writes now run in-turn (no longer queued)
    assert gate.allow("files__write_file", {"path": "b.md", "content": "x"}) is True


def test_multiple_pending_are_each_prompted():
    gate = _queued_gate("a.md", "b.md")
    provider, controller = _Provider(), _Controller(["once", "skip"])  # apply a, skip b
    loop._process_pending_writes(gate, provider, controller)
    assert provider.applied == [("files__write_file", {"path": "a.md", "content": "hi"})]
    assert len(controller.seen) == 2


def test_no_gate_or_provider_is_a_noop():
    loop._process_pending_writes(None, _Provider(), _Controller([]))
    loop._process_pending_writes(_queued_gate("a.md"), None, _Controller([]))  # no crash


class _PreviewController:
    def __init__(self):
        self.shown: list[tuple] = []

    def show_preview(self, path, diff, action="update", window=10):
        self.shown.append((path, action, diff))


def test_show_previews_renders_each_dry_run_frame():
    gate = ToolPermissions()
    gate.add_preview("docs/x.md", "[dry run — would create]\n+hi")
    gate.add_preview("y.md", "[dry run — would update]\n-old\n+new")
    ctrl = _PreviewController()
    loop._show_previews(gate, ctrl)
    assert [s[0] for s in ctrl.shown] == ["docs/x.md", "y.md"]
    assert ctrl.shown[0][1] == "create" and ctrl.shown[1][1] == "update"
    assert "+hi" in ctrl.shown[0][2] and "[dry run" not in ctrl.shown[0][2]  # banner stripped
    assert gate.previews == []          # drained


def test_show_previews_noop_without_gate():
    loop._show_previews(None, _PreviewController())    # no crash
