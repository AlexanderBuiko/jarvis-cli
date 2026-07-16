"""summarize_diff + the bordered write-approval frame (jarvis/repl/input.py)."""

from jarvis.repl.input import summarize_diff, frame_rows, _box_width


def _line(row):
    return "".join(text for _cls, text in row)


def _make_rows(action="create", expanded=False, n=30, window=10):
    body = [f"+line {i}" for i in range(n)]
    return frame_rows("docs/adr/x.md", action, body, n, 0, expanded, window,
                      ("w.keys", "[Enter] apply"))


def test_frame_is_bordered_and_fixed_width():
    rows = _make_rows()
    lines = [_line(r) for r in rows]
    assert lines[0].startswith("╭") and lines[0].endswith("╮")
    assert lines[-1].startswith("╰") and lines[-1].endswith("╯")
    width = _box_width()
    assert all(len(ln) == width for ln in lines)          # every row same width


def test_frame_title_shows_action_and_path():
    top = _line(_make_rows(action="delete")[0])
    assert "delete" in top and "docs/adr/x.md" in top


def test_collapsed_frame_truncates_with_more_line():
    rows = _make_rows(expanded=False, n=30, window=10)
    text = "\n".join(_line(r) for r in rows)
    assert "more line(s)" in text
    # 10 shown content lines + top + more + footer + bottom
    assert sum(1 for r in rows if "line 0" in _line(r)) == 1


def test_expanded_frame_shows_everything():
    rows = _make_rows(expanded=True, n=30, window=10)
    text = "\n".join(_line(r) for r in rows)
    assert "more line(s)" not in text
    assert "line 29" in text                               # last line visible


def test_counts_added_and_removed_and_drops_headers():
    diff = (
        "--- a/f.md\n"
        "+++ b/f.md\n"
        "@@ -1,2 +1,3 @@\n"
        " context line\n"
        "-old line\n"
        "+new line one\n"
        "+new line two\n"
    )
    body, added, removed = summarize_diff(diff)
    assert added == 2
    assert removed == 1
    # header lines are dropped; content (incl. the context line) is kept
    assert not any(b.startswith(("--- ", "+++ ", "@@")) for b in body)
    assert " context line" in body
    assert "+new line one" in body


def test_new_file_is_all_additions():
    diff = "--- a/new.md\n+++ b/new.md\n@@ -0,0 +1,2 @@\n+# Title\n+\n"
    body, added, removed = summarize_diff(diff)
    assert added == 2 and removed == 0
    assert body == ["+# Title", "+"]
