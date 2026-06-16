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

from typing import Callable

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.bindings.emacs import load_emacs_bindings
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
    "task":    {"new": {}, "list": {}, "show": {}, "start": {}, "next": {}, "back": {}, "pause": {}, "delete": {}, "done": {}, "todo": {}},
    "memory":  {"list": {}, "init": {}, "edit": {}, "show": {}, "load": {}, "unload": {}, "write": {}, "append": {}, "delete": {}},
    "personalize": {},
    "help":    {},
    "exit":    {},
}

MAX_SUGGESTIONS = 5
SUGGESTION_COLOR = "#a1a9b7"


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

    def __init__(self, status_fn: Callable[[], str] | None = None) -> None:
        self._status_fn = status_fn

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

    # ── Application construction ──────────────────────────────────────────────

    def _build_app(self) -> Application:
        has_suggestions = Condition(lambda: bool(self._suggestions))

        prefix_window = Window(
            content=FormattedTextControl(self._render_prefix),
            width=2,
            dont_extend_width=True,
        )

        is_empty = Condition(lambda: self._buffer.text == "")

        input_window = FloatContainer(
            content=Window(
                content=BufferControl(buffer=self._buffer),
                height=Dimension(min=1, max=1),
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
                    left=0,
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
            VSplit([prefix_window, input_window]),
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

    def _render_hint(self) -> FormattedText:
        text = (
            "Enter a request for the assistant..."
            if self._mode == "prompt"
            else "Enter a command..."
        )
        return FormattedText([("class:hint", text)])

    def _render_prefix(self) -> FormattedText:
        glyph = ">" if self._mode == "prompt" else "!"
        return FormattedText([("", glyph + " ")])

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
            text = self._buffer.text.strip()
            if not text:
                return
            hist = self._prompt_hist if self._mode == "prompt" else self._command_hist
            _add_history(hist, text)
            self._result = text
            event.app.exit()

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
