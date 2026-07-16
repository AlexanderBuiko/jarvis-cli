"""Tests for the local project-files MCP server (jarvis/mcp_servers/files_server.py).

Each test points JARVIS_FILES_ROOT at a tmp tree, so the tools operate in isolation.
"""

import pytest

from jarvis.mcp_servers import files_server


@pytest.fixture(autouse=True)
def _clean_journal():
    # The edit journal is process-global; reset it around every test.
    files_server.clear_journal()
    yield
    files_server.clear_journal()


def _tree(root):
    (root / "pkg").mkdir()
    (root / "pkg" / "a.py").write_text("import os\nprint(build_rag_block())\n")
    (root / "pkg" / "b.py").write_text("x = 1\nresult = build_rag_block(x)\n")
    (root / "README.md").write_text("# Title\n\nHello.\n")


def test_list_files_skips_noise(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")
    out = files_server.list_files("**/*")
    assert "pkg/a.py" in out and "README.md" in out
    assert ".git/config" not in out            # VCS internals filtered


def test_read_file(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    assert "Hello." in files_server.read_file("README.md")
    assert files_server.read_file("nope.md").startswith("error:")


def test_search_files_matches_across_files(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    out = files_server.search_files("build_rag_block", glob="**/*.py")
    lines = out.splitlines()
    files = {ln.split(":", 1)[0] for ln in lines}
    assert {"pkg/a.py", "pkg/b.py"} <= files      # found in both files
    assert all(":" in ln for ln in lines)         # path:line: text shape


def test_search_files_regex(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    out = files_server.search_files(r"result\s*=", glob="**/*.py", regex=True)
    assert "pkg/b.py" in out and "pkg/a.py" not in out


def test_write_file_create_returns_diff_and_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    out = files_server.write_file("docs/new.md", "# New\n")
    assert "created" in out and "+# New" in out
    assert (tmp_path / "docs" / "new.md").read_text() == "# New\n"


def test_write_file_modify_diff(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    out = files_server.write_file("README.md", "# Title\n\nGoodbye.\n")
    assert "updated" in out
    assert "-Hello." in out and "+Goodbye." in out
    assert "Goodbye." in (tmp_path / "README.md").read_text()


def test_write_file_dry_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    out = files_server.write_file("README.md", "# Changed\n", dry_run=True)
    assert "dry run" in out.lower()
    assert "# Title" in (tmp_path / "README.md").read_text()   # unchanged on disk


def test_write_file_noop_when_identical(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    out = files_server.write_file("README.md", "# Title\n\nHello.\n")
    assert "no changes" in out.lower()


def test_revert_modify_restores_prior_text(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    files_server.write_file("README.md", "# Title\n\nGoodbye.\n")
    out = files_server.revert_file("README.md")
    assert "reverted" in out.lower()
    assert (tmp_path / "README.md").read_text() == "# Title\n\nHello.\n"


def test_revert_created_file_deletes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    files_server.write_file("docs/adr/0001-x.md", "# ADR\n")
    assert (tmp_path / "docs" / "adr" / "0001-x.md").exists()
    out = files_server.revert_file("docs/adr/0001-x.md")
    assert "removed" in out.lower()
    assert not (tmp_path / "docs" / "adr" / "0001-x.md").exists()


def test_list_changes_and_revert_last(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    files_server.write_file("README.md", "# Title\n\nEdited.\n")
    files_server.write_file("NEW.md", "new\n")
    changes = files_server.list_changes()
    assert "updated README.md" in changes and "created NEW.md" in changes
    files_server.revert_last()                       # undoes the NEW.md create
    assert not (tmp_path / "NEW.md").exists()
    assert "Edited." in (tmp_path / "README.md").read_text()   # README still edited


def test_revert_with_no_history(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    assert "no recorded change" in files_server.revert_file("README.md").lower()
    assert "no file changes" in files_server.revert_last().lower()


def test_revert_guards_later_hand_edits(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    files_server.write_file("README.md", "# Title\n\nAssistant.\n")
    (tmp_path / "README.md").write_text("# Title\n\nHand-edited later.\n")   # user edits
    guarded = files_server.revert_file("README.md")
    assert "force=true" in guarded.lower()
    assert "Hand-edited later." in (tmp_path / "README.md").read_text()      # untouched
    forced = files_server.revert_file("README.md", force=True)
    assert "reverted" in forced.lower()
    assert (tmp_path / "README.md").read_text() == "# Title\n\nHello.\n"


def test_revert_steps_back_through_multiple_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    files_server.write_file("f.md", "v1\n")          # create
    files_server.write_file("f.md", "v2\n")          # modify
    files_server.revert_file("f.md")                 # undo modify → v1
    assert (tmp_path / "f.md").read_text() == "v1\n"
    files_server.revert_file("f.md")                 # undo create → gone
    assert not (tmp_path / "f.md").exists()


def test_delete_file_removes_and_shows_diff(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    out = files_server.delete_file("README.md")
    assert "deleted" in out.lower()
    assert "-# Title" in out                              # removal diff
    assert not (tmp_path / "README.md").exists()


def test_delete_dry_run_keeps_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    out = files_server.delete_file("README.md", dry_run=True)
    assert "dry run" in out.lower()
    assert (tmp_path / "README.md").exists()              # untouched


def test_delete_missing_file_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    assert files_server.delete_file("nope.md").startswith("error:")


def test_delete_directory_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    out = files_server.delete_file("pkg")                 # a directory
    assert out.startswith("error:")
    assert (tmp_path / "pkg").is_dir()


def test_delete_is_revertible(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(tmp_path))
    _tree(tmp_path)
    original = (tmp_path / "README.md").read_text()
    files_server.delete_file("README.md")
    assert "deleted README.md" in files_server.list_changes()
    out = files_server.revert_file("README.md")           # restore the deleted file
    assert "reverted" in out.lower()
    assert (tmp_path / "README.md").read_text() == original


def test_delete_outside_root_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("secret\n")
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(root))
    assert files_server.delete_file("../secret.txt").startswith("error:")
    assert (tmp_path / "secret.txt").exists()             # not deleted


def test_path_escaping_root_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("top secret\n")
    monkeypatch.setenv("JARVIS_FILES_ROOT", str(root))
    assert files_server.read_file("../secret.txt").startswith("error:")
    assert files_server.write_file("../evil.txt", "x").startswith("error:")
    assert not (tmp_path / "evil.txt").exists()
