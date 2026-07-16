"""
Terminal input controller.

Two explicit modes, toggled by typing ! on an empty buffer:
  prompt mode   — prefix ">", input forwarded to the agent
  command mode  — prefix "!", input dispatched to the REPL

The mode is stored as state; nothing is inferred from buffer content.

History is session-scoped and kept separate per mode.
↑/↓ navigate history only when the buffer is empty.

Command autocomplete (command mode only):
  Suggestions appear as plain text directly below the input line.
  ↑/↓ move the selection arrow when suggestions are visible.
  Tab accepts the selected suggestion and automatically shows the next level.
"""

from __future__ import annotations

import shutil
import sys
from typing import Callable

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.bindings.emacs import load_emacs_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import ConditionalContainer, Float, FloatContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout import Layout
from prompt_toolkit.styles import Style

# ── Command tree ──────────────────────────────────────────────────────────────
# Each key is a command token; the value is a dict of its sub-commands.
# An empty dict {} marks a leaf node.

COMMAND_TREE: dict[str, dict] = {
    "session": {"chat": {}, "summary": {}, "api": {}},
    "thread":  {"summary": {}, "load": {}, "new": {}, "clear": {}, "rename": {}, "delete": {}},
    "config":  {"show": {}, "set": {}, "update": {}, "reset": {}},
    "task":    {"new": {}, "list": {}, "show": {}, "start": {}, "run": {}, "exit": {}, "delete": {}, "attach": {}, "detach": {}},
    "invariants": {"show": {}, "init": {}},
    "profile": {"show": {}, "onboard": {}},
    "mcp":     {"list": {}, "call": {}},
    "index":   {"build": {}, "list": {}, "show": {}, "search": {}, "compare": {}, "delete": {}},
    "rag":     {"ask": {}, "eval": {}},
    "personalize": {},
    "help":    {},
    "exit":    {},
}

MAX_SUGGESTIONS = 5
SUGGESTION_COLOR = "#a1a9b7"

# The input line soft-wraps and grows up to this many visual rows.
MAX_INPUT_ROWS = 5
# A clipboard paste at or above this many characters is collapsed to a short
# placeholder in the buffer (the real text is restored on submit).
PASTE_COLLAPSE_THRESHOLD = 1000


# ── Suggestion logic ──────────────────────────────────────────────────────────


def get_suggestions(text: str) -> list[str]:
    """Return up to MAX_SUGGESTIONS completions for the given command text.

    text is the raw buffer content (no prefix).
    A trailing space means the user has confirmed the previous token and
    expects completions at the next level.
    """
    has_trailing = text.endswith(" ")
    tokens = text.split()

    tree = COMMAND_TREE

    if not tokens:
        return list(tree)[:MAX_SUGGESTIONS]

    if has_trailing:
        for token in tokens:
            matches = [k for k in tree if k.startswith(token)]
            if len(matches) == 1 and matches[0] == token:
                tree = tree[token]
            else:
                return []
        return list(tree)[:MAX_SUGGESTIONS]

    for token in tokens[:-1]:
        matches = [k for k in tree if k.startswith(token)]
        if len(matches) == 1 and matches[0] == token:
            tree = tree[token]
        else:
            return []

    last = tokens[-1]
    matches = [k for k in tree if k.startswith(last)]

    if len(matches) == 1 and matches[0] == last:
        return list(tree[last])[:MAX_SUGGESTIONS]

    return matches[:MAX_SUGGESTIONS]


def apply_suggestion(text: str, suggestion: str) -> str:
    """Return the new command text after accepting suggestion."""
    has_trailing = text.endswith(" ")
    tokens = text.split()

    if not tokens or has_trailing:
        return text + suggestion

    tree = COMMAND_TREE
    for token in tokens[:-1]:
        if token in tree:
            tree = tree[token]
        else:
            break

    last = tokens[-1]
    if last in tree:
        return text + " " + suggestion
    else:
        prefix_tokens = tokens[:-1]
        if prefix_tokens:
            return " ".join(prefix_tokens) + " " + suggestion
        return suggestion


# ── Diff preview ──────────────────────────────────────────────────────────────


def summarize_diff(diff: str) -> tuple[list[str], int, int]:
    """Split a unified diff into displayable body lines + (added, removed) counts.

    Drops the ``--- a/…`` / ``+++ b/…`` / ``@@`` header lines so the preview shows only
    the changed content — the useful part for a compact frame.
    """
    body: list[str] = []
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith(("--- ", "+++ ", "@@")):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
        body.append(line)
    return body, added, removed


# ── Write-approval frame ────────────────────────────────────────────────────────
# A bordered box around the diff, coloured by the action (create/update/delete). The
# same rows drive both the live prompt_toolkit frame and the static block that stays in
# the chat after a decision.

_BOX_MIN_W, _BOX_MAX_W = 44, 100
# action → (label, box symbol). Border colour comes from the style classes below.
_ACTIONS = {"create": ("create", "+"), "update": ("update", "~"), "delete": ("delete", "-")}
# style class → ANSI code, for the static (post-decision) reprint.
_FRAME_ANSI = {
    "create": "\033[32m", "update": "\033[33m", "delete": "\033[31m",
    "w.add": "\033[32m", "w.del": "\033[31m", "w.ctx": "\033[90m",
    "w.more": "\033[94m", "w.keys": "\033[96m",
}
_FRAME_STYLE = {
    "create": "#98c379 bold", "update": "#e5c07b bold", "delete": "#e06c75 bold",
    "w.add": "#98c379", "w.del": "#e06c75", "w.ctx": "#7f848e",
    "w.more": "#8b9dc3 italic", "w.keys": "#8b9dc3 bold",
}


def _box_width() -> int:
    return max(_BOX_MIN_W, min(_BOX_MAX_W, shutil.get_terminal_size((80, 24)).columns))


def _fit(text: str, width: int) -> str:
    """Truncate (with …) or right-pad ``text`` to exactly ``width`` columns."""
    if width <= 0:
        return ""
    if len(text) > width:
        return text[: width - 1] + "…" if width > 1 else text[:width]
    return text.ljust(width)


def frame_rows(
    path: str, action: str, body: list[str], added: int, removed: int,
    expanded: bool, window: int, footer: tuple[str, str],
) -> list[list[tuple[str, str]]]:
    """Build the bordered box as rows of ``(style_class, text)`` segments.

    ``footer`` is the (class, text) shown on the last inner row — the key hints while
    live, or the decision once decided. Border/title use the action's colour class;
    content lines are coloured by +/-.
    """
    label, sym = _ACTIONS.get(action, _ACTIONS["update"])
    width = _box_width()
    cw = width - 4  # "│ " + content + " │"
    shown = body if expanded else body[:window]
    hidden = 0 if expanded else max(0, len(body) - window)

    rows: list[list[tuple[str, str]]] = []
    top_text = f"─ {sym} {label}: {path}  (+{added} −{removed}) "
    top_text = top_text[: width - 2]
    rows.append([(action, "╭" + top_text + "─" * (width - 2 - len(top_text)) + "╮")])
    for line in shown:
        cls = "w.add" if line.startswith("+") else "w.del" if line.startswith("-") else "w.ctx"
        rows.append([(action, "│ "), (cls, _fit(line, cw)), (action, " │")])
    if hidden:
        note = f"… {hidden} more line(s) · Ctrl+S to expand"
        rows.append([(action, "│ "), ("w.more", _fit(note, cw)), (action, " │")])
    elif expanded and len(body) > window:
        rows.append([(action, "│ "), ("w.more", _fit("Ctrl+S to collapse", cw)), (action, " │")])
    rows.append([(action, "│ "), (footer[0], _fit(footer[1], cw)), (action, " │")])
    rows.append([(action, "╰" + "─" * (width - 2) + "╯")])
    return rows


def _rows_to_ansi(rows: list[list[tuple[str, str]]]) -> str:
    """Render frame rows as a static string (ANSI-coloured only when stdout is a TTY)."""
    colour = sys.stdout.isatty()
    out = []
    for row in rows:
        line = "".join(
            (f"{_FRAME_ANSI.get(cls, '')}{text}\033[0m" if colour else text)
            for cls, text in row
        )
        out.append(line)
    return "\n".join(out)


# ── InputController ───────────────────────────────────────────────────────────


class InputController:
    """
    Custom prompt_toolkit Application with explicit prompt/command modes.

    Mode persists across submissions. Typing ! on an empty buffer toggles mode.
    The prefix glyph (> or !) is rendered by the UI, never stored in the buffer.

    read_input() blocks until the user submits input and returns
    (input_type, text) where:
      input_type  "prompt"  or  "command"
      text        raw buffer content, stripped
    """

    def __init__(
        self,
        status_fn: Callable[[], str] | None = None,
        progress_fn: Callable[[], str] | None = None,
        hint_fn: Callable[[], str] | None = None,
    ) -> None:
        self._status_fn = status_fn
        self._progress_fn = progress_fn
        # Optional context-aware placeholder; overrides the default when non-empty.
        self._hint_fn = hint_fn

        # ── Mode ──────────────────────────────────────────────────────────────
        self._mode: str = "prompt"  # "prompt" | "command"

        # ── History ───────────────────────────────────────────────────────────
        self._prompt_hist: list[str] = []
        self._command_hist: list[str] = []
        self._prompt_ptr: int = -1   # -1 = not navigating
        self._command_ptr: int = -1
        self._saved_input: str = ""  # buffer text before navigation started

        # ── Suggestion state ──────────────────────────────────────────────────
        self._suggestions: list[str] = []
        self._suggestion_idx: int = 0

        # ── Result communicated from Enter handler ────────────────────────────
        self._result: str = ""

        # ── Collapsed clipboard pastes (placeholder text -> real text) ────────
        self._pastes: dict[str, str] = {}
        self._paste_seq: int = 0

        # ── Build Application ─────────────────────────────────────────────────
        self._buffer = Buffer(
            name="input",
            multiline=False,
            on_text_changed=self._on_text_changed,
        )
        self._app = self._build_app()

    # ── Public ────────────────────────────────────────────────────────────────

    def read_input(self) -> tuple[str, str]:
        """Block until the user submits a non-empty input.

        Returns ("prompt", text) or ("command", text).
        Raises EOFError on Ctrl+D.
        """
        while True:
            self._result = ""
            self._buffer.set_document(Document(""), bypass_readonly=False)
            self._suggestions = []
            self._suggestion_idx = 0
            self._prompt_ptr = -1
            self._command_ptr = -1
            self._saved_input = ""

            try:
                self._app.run()
            except KeyboardInterrupt:
                continue
            except EOFError:
                raise

            text = self._result
            if not text:
                continue

            return self._mode, text

    # ── Inline selection / single-line prompts (used by the task driver) ──────────

    def select(self, title: str, options: list[str], default: int = 0) -> int | None:
        """Show a vertical option list; ↑/↓ moves the arrow, Enter selects.

        Returns the chosen index, or None if cancelled (Ctrl+C / Ctrl+D).
        """
        state = {"idx": max(0, min(default, len(options) - 1))}
        kb = KeyBindings()

        @kb.add("up", eager=True)
        def _up(event) -> None:
            state["idx"] = (state["idx"] - 1) % len(options)
            event.app.invalidate()

        @kb.add("down", eager=True)
        def _down(event) -> None:
            state["idx"] = (state["idx"] + 1) % len(options)
            event.app.invalidate()

        @kb.add("enter")
        def _enter(event) -> None:
            event.app.exit(result=state["idx"])

        @kb.add("c-c")
        @kb.add("c-d")
        def _cancel(event) -> None:
            event.app.exit(result=None)

        def render() -> FormattedText:
            items: list = [("class:select.title", title + "\n")]
            for i, opt in enumerate(options):
                active = i == state["idx"]
                arrow = "→ " if active else "  "
                cls = "class:select.active" if active else "class:select.option"
                items.append((cls, f"{arrow}{opt}\n"))
            return FormattedText(items)

        app = Application(
            layout=Layout(HSplit([Window(
                content=FormattedTextControl(render),
                dont_extend_height=True,
                always_hide_cursor=True,  # don't park the cursor over the arrow glyph
            )])),
            key_bindings=kb,
            style=Style.from_dict({
                "select.title": "#8b9dc3 bold",
                "select.option": "",
                "select.active": "#e5c07b bold",
            }),
            full_screen=False,
            erase_when_done=True,  # remove the arrow menu once a choice is made
            mouse_support=False,
        )
        return app.run()

    def approve_write(self, path: str, diff: str, action: str = "update",
                      window: int = 10) -> str:
        """Approve a pending file change from a bordered, expandable diff frame.

        The frame is drawn as a box coloured by ``action`` (create / update / delete),
        showing the first ``window`` changed lines (the rest behind a "… N more" line).
        Ctrl+S (or ``e``) expands/collapses it — only this live frame responds to the
        toggle; already-decided frames are frozen. Keys: Enter = apply once, ``a`` =
        apply and allow all this session, ``s`` (or Ctrl+C) = skip. After the decision
        the frame is **reprinted as a static block that stays in the chat**, footered
        with the choice. Returns ``"once"`` / ``"always"`` / ``"skip"``.
        """
        body, added, removed = summarize_diff(diff)
        state = {"expanded": False, "result": "skip"}
        kb = KeyBindings()

        def _finish(result: str):
            def handler(event) -> None:
                state["result"] = result
                event.app.exit(result=result)
            return handler

        kb.add("enter")(_finish("once"))
        kb.add("a")(_finish("always"))
        kb.add("s")(_finish("skip"))
        kb.add("c-c")(_finish("skip"))
        kb.add("c-d")(_finish("skip"))

        @kb.add("c-s")
        @kb.add("e")
        def _toggle(event) -> None:
            state["expanded"] = not state["expanded"]
            event.app.invalidate()

        keys = "[Enter] apply   [a] allow all this session   [s] skip"

        def render() -> FormattedText:
            rows = frame_rows(path, action, body, added, removed,
                              state["expanded"], window, ("w.keys", keys))
            items: list = []
            for row in rows:
                for cls, text in row:
                    items.append((f"class:{cls}", text))
                items.append(("", "\n"))
            return FormattedText(items)

        app = Application(
            layout=Layout(HSplit([Window(
                content=FormattedTextControl(render),
                dont_extend_height=True,
                always_hide_cursor=True,
            )])),
            key_bindings=kb,
            style=Style.from_dict(_FRAME_STYLE),
            full_screen=False,
            erase_when_done=True,  # erase the *live* frame; we reprint a static one below
            mouse_support=False,
        )
        app.run()

        # Persist the frame in the chat (it doesn't vanish once decided), footered with
        # the decision instead of the key hints — in whatever expand state it was left.
        decided = {"once": "→ applied", "always": "→ applied · allowing all this session",
                   "skip": "→ skipped"}[state["result"]]
        rows = frame_rows(path, action, body, added, removed,
                          state["expanded"], window, ("w.keys", decided))
        print(_rows_to_ansi(rows))
        return state["result"]

    def show_preview(self, path: str, diff: str, action: str = "update",
                     window: int = 10) -> None:
        """Show a dry-run diff in a read-only, expandable frame (nothing is written).

        Same bordered box as ``approve_write`` but with no apply/skip — just **Ctrl+S**
        (or ``e``) to expand/collapse and **Enter** to continue. The frame then stays in
        the chat, footered "dry run — not written".
        """
        body, added, removed = summarize_diff(diff)
        state = {"expanded": False}
        kb = KeyBindings()

        for key in ("enter", "c-c", "c-d", "s"):
            kb.add(key)(lambda event: event.app.exit())

        @kb.add("c-s")
        @kb.add("e")
        def _toggle(event) -> None:
            state["expanded"] = not state["expanded"]
            event.app.invalidate()

        foot = "dry run — not written   ·   Ctrl+S expand   ·   [Enter] continue"

        def render() -> FormattedText:
            rows = frame_rows(path, action, body, added, removed,
                              state["expanded"], window, ("w.more", foot))
            items: list = []
            for row in rows:
                for cls, text in row:
                    items.append((f"class:{cls}", text))
                items.append(("", "\n"))
            return FormattedText(items)

        app = Application(
            layout=Layout(HSplit([Window(
                content=FormattedTextControl(render),
                dont_extend_height=True, always_hide_cursor=True,
            )])),
            key_bindings=kb,
            style=Style.from_dict(_FRAME_STYLE),
            full_screen=False,
            erase_when_done=True,
            mouse_support=False,
        )
        app.run()
        rows = frame_rows(path, action, body, added, removed,
                          state["expanded"], window, ("w.more", "→ dry run (not written)"))
        print(_rows_to_ansi(rows))

    def read_text(self, label: str) -> str:
        """Prompt for a single free-text line (e.g. 'What's the problem?'). Returns the text."""
        buffer = Buffer(name="freetext", multiline=False)
        kb = merge_key_bindings([self._freetext_bindings(buffer), load_emacs_bindings()])

        prefix = Window(
            content=FormattedTextControl(lambda: FormattedText([("class:freetext.label", label + " ")])),
            dont_extend_width=True,
            width=len(label) + 1,
        )
        field = Window(
            content=BufferControl(buffer=buffer),
            height=Dimension(min=1, max=MAX_INPUT_ROWS),
            wrap_lines=True,
            dont_extend_height=True,
        )
        app = Application(
            layout=Layout(VSplit([prefix, field]), focused_element=buffer),
            key_bindings=kb,
            style=Style.from_dict({"freetext.label": "#8b9dc3 bold"}),
            full_screen=False,
            mouse_support=False,
        )
        result: dict = {}

        def _run() -> str:
            app.run()
            return result.get("text", "")

        # Stash the result via the binding closure.
        self._freetext_result = result
        return _run().strip()

    def _freetext_bindings(self, buffer: Buffer) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("enter")
        def _enter(event) -> None:
            self._freetext_result["text"] = buffer.text
            event.app.exit()

        @kb.add("c-c")
        @kb.add("c-d")
        def _cancel(event) -> None:
            self._freetext_result["text"] = ""
            event.app.exit()

        return kb

    # ── Application construction ──────────────────────────────────────────────

    def _build_app(self) -> Application:
        has_suggestions = Condition(lambda: bool(self._suggestions))

        is_empty = Condition(lambda: self._buffer.text == "")

        # The prompt glyph is rendered as a per-line prefix *inside* the buffer
        # window (not a separate column), so prompt_toolkit accounts for its
        # width in cursor positioning even when the input soft-wraps. Wrapped
        # continuation rows are indented to align under the first character.
        input_window = FloatContainer(
            content=Window(
                content=BufferControl(buffer=self._buffer),
                # Soft-wrap long input and grow up to MAX_INPUT_ROWS rows;
                # beyond that the window scrolls to keep the cursor visible.
                height=Dimension(min=1, max=MAX_INPUT_ROWS),
                wrap_lines=True,
                get_line_prefix=self._line_prefix,
                dont_extend_height=True,
            ),
            floats=[
                Float(
                    content=ConditionalContainer(
                        Window(
                            content=FormattedTextControl(self._render_hint),
                            dont_extend_height=True,
                        ),
                        filter=is_empty,
                    ),
                    # Offset past the "> " prefix on the first row.
                    left=2,
                    top=0,
                )
            ],
        )

        suggestions_window = ConditionalContainer(
            Window(
                content=FormattedTextControl(self._render_suggestions),
                dont_extend_height=True,
            ),
            filter=has_suggestions,
        )

        has_progress = Condition(lambda: bool(self._progress_fn and self._progress_fn()))
        progress_window = ConditionalContainer(
            Window(
                content=FormattedTextControl(self._render_progress),
                dont_extend_height=True,
            ),
            filter=has_progress,
        )

        containers = []
        if self._status_fn is not None:
            containers.append(
                Window(
                    content=FormattedTextControl(self._render_status),
                    height=1,
                    dont_extend_height=True,
                )
            )
        containers += [
            progress_window,
            input_window,
            suggestions_window,
        ]

        layout = Layout(
            HSplit(containers),
            focused_element=self._buffer,
        )

        kb = merge_key_bindings([self._build_key_bindings(), load_emacs_bindings()])

        style = Style.from_dict({
            "suggestion": SUGGESTION_COLOR,
            "hint": "#6b7280 italic",
            "status": "#8b9dc3",
            "progress.header": "#8b9dc3 bold",
            "progress.done": "#98c379",        # green
            "progress.current": "#e5c07b bold",  # amber
            "progress.pending": "#6b7280",      # grey
        })

        return Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            full_screen=False,
            mouse_support=False,
        )

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render_status(self) -> FormattedText:
        text = self._status_fn() if self._status_fn else ""
        try:
            from prompt_toolkit.application import get_app
            width = get_app().output.get_size().columns
        except Exception:
            width = 80
        padded = text.ljust(width)
        return FormattedText([("class:status", padded)])

    def _render_progress(self) -> FormattedText:
        """Render the plan-progress panel, colouring each line by its status glyph."""
        text = self._progress_fn() if self._progress_fn else ""
        if not text:
            return FormattedText([])
        glyph_class = {
            "✓": "class:progress.done",
            "▶": "class:progress.current",
            "○": "class:progress.pending",
        }
        items = []
        for line in text.split("\n"):
            cls = glyph_class.get(line.lstrip()[:1], "class:progress.header")
            items.append((cls, line + "\n"))
        return FormattedText(items)

    def _render_hint(self) -> FormattedText:
        if self._mode == "command":
            return FormattedText([("class:hint", "Enter a command...")])
        # Prompt mode: a context-aware hint (e.g. an in-progress task) wins.
        contextual = self._hint_fn() if self._hint_fn else ""
        text = contextual or "Enter a request for the assistant..."
        return FormattedText([("class:hint", text)])

    def _line_prefix(self, line_number: int, wrap_count: int) -> FormattedText:
        """Per-line prefix for the input window.

        The prompt glyph ("> " or "! ") is shown on the very first visual row.
        Wrapped/continuation rows get no prefix, so long input does not pick up
        stray leading spaces. Rendering this inside the window keeps the cursor
        correct when the input wraps.
        """
        if line_number == 0 and wrap_count == 0:
            glyph = ">" if self._mode == "prompt" else "!"
            return FormattedText([("", glyph + " ")])
        return FormattedText([("", "")])

    def _render_suggestions(self) -> FormattedText:
        items = []
        for i, suggestion in enumerate(self._suggestions):
            arrow = "→ " if i == self._suggestion_idx else "  "
            items.append(("class:suggestion", f"{arrow}{suggestion}\n"))
        return FormattedText(items)

    # ── Key bindings ──────────────────────────────────────────────────────────

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("!")
        def _exclamation(event) -> None:
            if self._buffer.text == "":
                # Empty buffer — toggle mode.
                self._mode = "command" if self._mode == "prompt" else "prompt"
                self._suggestions = []
                self._suggestion_idx = 0
                self._prompt_ptr = -1
                self._command_ptr = -1
                event.app.invalidate()
            else:
                self._buffer.insert_text("!")

        @kb.add("enter")
        def _enter(event) -> None:
            display = self._buffer.text.strip()
            if not display:
                return
            # History keeps the compact (collapsed) form; the agent receives the
            # expanded text with any collapsed pastes restored to their content.
            hist = self._prompt_hist if self._mode == "prompt" else self._command_hist
            _add_history(hist, display)
            self._result = self._expand_pastes(self._buffer.text).strip()
            # Clear the suggestion overlay so the accepted command's selection
            # block does not linger above the printed output.
            self._suggestions = []
            self._suggestion_idx = 0
            event.app.invalidate()
            event.app.exit()

        @kb.add(Keys.BracketedPaste)
        def _paste(event) -> None:
            data = event.data
            if len(data) >= PASTE_COLLAPSE_THRESHOLD:
                placeholder = self._register_paste(data)
                self._buffer.insert_text(placeholder)
            else:
                self._buffer.insert_text(data)

        @kb.add("up", eager=True)
        def _up(event) -> None:
            if self._suggestions:
                self._suggestion_idx = (
                    (self._suggestion_idx - 1) % len(self._suggestions)
                )
                event.app.invalidate()
                return

            hist = self._prompt_hist if self._mode == "prompt" else self._command_hist
            ptr_attr = "_prompt_ptr" if self._mode == "prompt" else "_command_ptr"
            ptr = getattr(self, ptr_attr)

            # Allow navigation only when buffer is empty OR already navigating.
            if self._buffer.text != "" and ptr == -1:
                return

            if not hist:
                return
            if ptr == -1:
                self._saved_input = self._buffer.text
                ptr = len(hist) - 1
            elif ptr > 0:
                ptr -= 1
            setattr(self, ptr_attr, ptr)
            entry = hist[ptr]
            self._buffer.set_document(Document(entry, cursor_position=len(entry)))

        @kb.add("down", eager=True)
        def _down(event) -> None:
            if self._suggestions:
                self._suggestion_idx = (
                    (self._suggestion_idx + 1) % len(self._suggestions)
                )
                event.app.invalidate()
                return

            ptr_attr = "_prompt_ptr" if self._mode == "prompt" else "_command_ptr"
            ptr = getattr(self, ptr_attr)

            if ptr == -1:
                return

            hist = self._prompt_hist if self._mode == "prompt" else self._command_hist
            if ptr < len(hist) - 1:
                ptr += 1
                setattr(self, ptr_attr, ptr)
                entry = hist[ptr]
                self._buffer.set_document(Document(entry, cursor_position=len(entry)))
            else:
                setattr(self, ptr_attr, -1)
                self._buffer.set_document(
                    Document(self._saved_input,
                             cursor_position=len(self._saved_input))
                )

        @kb.add("tab", eager=True)
        def _tab(event) -> None:
            if self._mode != "command" or not self._suggestions:
                return
            text = self._buffer.text
            suggestion = self._suggestions[self._suggestion_idx]
            new_text = apply_suggestion(text, suggestion).rstrip() + " "
            self._buffer.set_document(Document(new_text, cursor_position=len(new_text)))
            next_suggestions = get_suggestions(new_text)
            self._suggestions = next_suggestions[:MAX_SUGGESTIONS]
            self._suggestion_idx = 0
            event.app.invalidate()

        @kb.add("c-c")
        def _ctrl_c(event) -> None:
            self._buffer.set_document(Document(""), bypass_readonly=False)
            self._suggestions = []
            self._prompt_ptr = -1
            self._command_ptr = -1
            event.app.invalidate()

        @kb.add("c-g", eager=True)
        def _ctrl_g(event) -> None:
            """Clear the input buffer and reset all navigation/suggestion state."""
            self._buffer.set_document(Document(""), bypass_readonly=False)
            self._suggestions = []
            self._suggestion_idx = 0
            self._prompt_ptr = -1
            self._command_ptr = -1
            self._saved_input = ""
            event.app.invalidate()

        @kb.add("c-d")
        def _ctrl_d(event) -> None:
            raise EOFError

        return kb

    # ── Clipboard paste collapsing ──────────────────────────────────────────────

    def _register_paste(self, data: str) -> str:
        """Store a large paste and return the placeholder shown in the buffer."""
        self._paste_seq += 1
        placeholder = f"[Pasted from clipboard: {len(data)} characters]"
        # Disambiguate the rare case of two same-length pastes coexisting.
        if placeholder in self._pastes and self._pastes[placeholder] != data:
            placeholder = f"[Pasted from clipboard: {len(data)} characters (#{self._paste_seq})]"
        self._pastes[placeholder] = data
        return placeholder

    def _expand_pastes(self, text: str) -> str:
        """Replace any paste placeholders in text with their real content."""
        for placeholder, real in self._pastes.items():
            if placeholder in text:
                text = text.replace(placeholder, real)
        return text

    # ── Buffer event ──────────────────────────────────────────────────────────

    def _on_text_changed(self, _buf: Buffer) -> None:
        """Recompute suggestions on every keystroke (command mode, non-empty buffer only)."""
        text = self._buffer.text
        if self._mode == "command" and text:
            self._suggestions = get_suggestions(text)[:MAX_SUGGESTIONS]
        else:
            self._suggestions = []
        self._suggestion_idx = 0


# ── Helpers ───────────────────────────────────────────────────────────────────


def _add_history(hist: list[str], entry: str) -> None:
    """Append entry to history, avoiding consecutive duplicates."""
    if hist and hist[-1] == entry:
        return
    hist.append(entry)
