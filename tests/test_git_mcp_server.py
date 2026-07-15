"""Tests for the local git MCP server tool (jarvis/mcp_servers/git_server.py)."""

import subprocess

from jarvis.mcp_servers import git_server


def _run(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def test_get_current_branch_reports_branch(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q")
    _run(repo, "git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "init")
    _run(repo, "git", "checkout", "-q", "-b", "feature/x")
    monkeypatch.setenv("GIT_REPO_PATH", str(repo))

    assert git_server.get_current_branch() == "feature/x"


def test_get_current_branch_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_REPO_PATH", str(tmp_path))
    result = git_server.get_current_branch()
    assert result.startswith("error:")
