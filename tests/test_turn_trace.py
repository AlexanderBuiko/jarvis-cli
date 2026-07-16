"""Live activity notes + the answer label (jarvis/repl/loop.py). Under pytest stdout
isn't a TTY, so colour is suppressed and we can assert on plain text."""

from jarvis.repl import loop, tool_trace


def test_tool_line_gets_the_tool_marker():
    assert loop._style_note("[1] files.write_file(path=x) → ok").startswith("  ")
    assert "🔧" in loop._style_note("[1] files.write_file(path=x) → ok")


def test_rag_line_gets_the_rag_marker():
    styled = loop._style_note("RAG: retrieved 4 chunk(s) from 'faq'")
    assert "📚" in styled
    assert "🔧" not in styled


def test_narration_line_gets_the_speech_marker():
    styled = loop._style_note("SAY: Let me read gateway.py to see the loop.")
    assert "💬" in styled
    assert "Let me read gateway.py" in styled
    assert "SAY:" not in styled                # prefix stripped
    assert "🔧" not in styled


def test_live_notes_drains_the_buffer():
    tool_trace.install()
    import logging
    logging.getLogger("jarvis.tools").info("[1] files.read_file(path=a) → ...")
    notes = loop._live_notes()
    assert any("🔧" in n for n in notes)
    assert loop._live_notes() == []          # buffer drained after reading


def test_format_answer_labels_the_answer():
    out = loop._format_answer("Hello there.")
    assert "Answer" in out.splitlines()[0]
    assert "Hello there." in out
